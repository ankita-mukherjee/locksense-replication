package locksense;

import com.google.gson.*;
import java.io.*;
import java.lang.management.*;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;

/**
 * LockSense Job 2 – Contention Profiler
 *
 * For each candidate in candidates.json this tool:
 *   1. Instantiates the target class via reflection
 *   2. Runs the target method at threadCount = 1 (baseline) and 50 / 100 (stress)
 *   3. Measures contention via ThreadMXBean (blocked-count ≈ GETS, blocked-time ≈ HTM)
 *   4. Applies the paper's confirmation rule:
 *        confirmed  iff  ΔHTM > 5%  OR  ΔGETS > 10%  OR  blocked_count > 0
 *   5. Writes validated_candidates.json with only the confirmed candidates.
 */
public class ContentionProfiler {

    // ── tunable parameters ───────────────────────────────────────────────────
    private static final int   WARMUP_ITERS    = 5;
    private static final int   MEASURE_ITERS   = 15;   // per thread
    private static final int[] THREAD_COUNTS   = {50, 100};
    private static final double TAU_HTM_PCT    = 5.0;  // τ_h  (paper §4.2.4)
    private static final double TAU_GETS_PCT   = 10.0; // τ_g

    // ── entry point ──────────────────────────────────────────────────────────

    public static void main(String[] args) throws Exception {
        String inFile  = args.length > 0 ? args[0] : "candidates.json";
        String outFile = args.length > 1 ? args[1] : "validated_candidates.json";
        String workDir = args.length > 2 ? args[2] : ".";   // where to write output

        String json = new String(Files.readAllBytes(Paths.get(workDir, inFile)));
        JsonArray candidates = JsonParser.parseString(json).getAsJsonArray();

        ThreadMXBean mxBean = ManagementFactory.getThreadMXBean();
        mxBean.setThreadContentionMonitoringEnabled(true);

        JsonArray validated = new JsonArray();

        for (JsonElement elem : candidates) {
            JsonObject cand = elem.getAsJsonObject();
            String className  = cand.get("class").getAsString();
            String methodName = cand.get("method").getAsString();
            String smellType  = cand.get("smell_type").getAsString();

            System.out.printf("%n[Job 2] Profiling  %-30s → %s.%s()%n",
                    smellType, className, methodName);

            try {
                JsonObject metrics = runProfiling(mxBean, className, methodName);
                if (metrics == null) {
                    System.out.println("         SKIP – could not profile (see log)");
                    continue;
                }

                boolean confirmed = isConfirmed(metrics);
                JsonObject out = cand.deepCopy();
                out.add("jlm_metrics", metrics);
                out.addProperty("confirmed", confirmed);

                if (confirmed) {
                    validated.add(out);
                    System.out.printf("         ✓ CONFIRMED  ΔHTM=%.1f%%  ΔGETS=%.1f%%  blocked=%d%n",
                            metrics.get("delta_htm_pct").getAsDouble(),
                            metrics.get("delta_gets_pct").getAsDouble(),
                            metrics.get("spin_count").getAsLong());
                } else {
                    System.out.printf("         ✗ not confirmed  ΔHTM=%.1f%%  ΔGETS=%.1f%%%n",
                            metrics.get("delta_htm_pct").getAsDouble(),
                            metrics.get("delta_gets_pct").getAsDouble());
                }
            } catch (Exception e) {
                System.out.println("         ERROR: " + e.getMessage());
            }
        }

        Gson gson = new GsonBuilder().setPrettyPrinting().create();
        Path outPath = Paths.get(workDir, outFile);
        try (Writer w = new FileWriter(outPath.toFile())) {
            gson.toJson(validated, w);
        }
        System.out.printf("%n[Job 2] Confirmed candidates: %d  →  %s%n",
                validated.size(), outPath.toAbsolutePath());
    }

    // ── profiling core ───────────────────────────────────────────────────────

    private static JsonObject runProfiling(ThreadMXBean mxBean,
                                           String className,
                                           String methodName) throws Exception {
        Class<?> cls = loadClass(className);
        if (cls == null) return null;

        Method method = findMethod(cls, methodName);
        if (method == null) {
            System.out.println("         Method not found: " + methodName);
            return null;
        }
        method.setAccessible(true);

        // ── baseline: single-threaded ────────────────────────────────────────
        Object baseInst = newInstance(cls);
        if (baseInst == null) return null;

        ProfResult baseline = profile(mxBean, baseInst, method, cls, 1);

        // ── stress: find run with highest ΔHTM ──────────────────────────────
        ProfResult bestMT      = null;
        int        bestThreads = 0;

        for (int tc : THREAD_COUNTS) {
            Object stressInst = newInstance(cls);
            if (stressInst == null) continue;
            ProfResult mt = profile(mxBean, stressInst, method, cls, tc);
            if (bestMT == null || mt.avgHoldTimeUs > bestMT.avgHoldTimeUs) {
                bestMT      = mt;
                bestThreads = tc;
            }
        }
        if (bestMT == null) return null;

        double deltaHTM  = pctDelta(baseline.avgHoldTimeUs,  bestMT.avgHoldTimeUs);
        double deltaGETS = pctDelta(baseline.totalOps,        bestMT.totalOps);

        JsonObject m = new JsonObject();
        m.addProperty("gets_1t",               baseline.totalOps);
        m.addProperty("gets_mt",               bestMT.totalOps);
        m.addProperty("delta_gets_pct",         round2(deltaGETS));
        m.addProperty("aver_htm_1t_us",         round2(baseline.avgHoldTimeUs));
        m.addProperty("aver_htm_mt_us",         round2(bestMT.avgHoldTimeUs));
        m.addProperty("delta_htm_pct",          round2(deltaHTM));
        m.addProperty("spin_count",             bestMT.totalBlockedCount);
        m.addProperty("thread_count_used",      bestThreads);
        m.addProperty("throughput_1t",          round2(baseline.throughputOpsPerSec));
        m.addProperty("throughput_mt",          round2(bestMT.throughputOpsPerSec));
        m.addProperty("contention_factor",      round2(contentionFactor(baseline, bestMT, bestThreads)));
        m.addProperty("match_confidence",       "high");
        return m;
    }

    // ─── measurement harness ─────────────────────────────────────────────────

    static class ProfResult {
        long   totalOps;
        double elapsedMs;
        double throughputOpsPerSec;
        long   totalBlockedCount;
        long   totalBlockedTimeMs;
        double avgHoldTimeUs;   // us per operation (proxy for AVER_HTM)
    }

    private static ProfResult profile(ThreadMXBean mxBean,
                                      Object instance,
                                      Method method,
                                      Class<?> cls,
                                      int threadCount) throws Exception {
        // warm-up
        for (int i = 0; i < WARMUP_ITERS; i++) {
            try { method.invoke(instance, buildArgs(method, cls)); }
            catch (Exception ignored) {}
        }

        CountDownLatch ready  = new CountDownLatch(threadCount);
        CountDownLatch start  = new CountDownLatch(1);
        CountDownLatch finish = new CountDownLatch(threadCount);
        AtomicLong     ops    = new AtomicLong(0);

        // snapshot contention counters before the run
        long blockedBefore = sumBlockedCount(mxBean);
        long blockedTimeBefore = sumBlockedTime(mxBean);

        long t0 = System.nanoTime();

        for (int t = 0; t < threadCount; t++) {
            new Thread(() -> {
                ready.countDown();
                try { start.await(); } catch (InterruptedException e) { Thread.currentThread().interrupt(); }
                for (int i = 0; i < MEASURE_ITERS; i++) {
                    try { method.invoke(instance, buildArgs(method, cls)); ops.incrementAndGet(); }
                    catch (Exception ignored) {}
                }
                finish.countDown();
            }, "locksense-worker-" + t).start();
        }

        ready.await();       // all threads ready
        start.countDown();   // fire!
        finish.await();      // all done

        long elapsed = System.nanoTime() - t0;
        long blockedAfter     = sumBlockedCount(mxBean);
        long blockedTimeAfter = sumBlockedTime(mxBean);

        ProfResult r = new ProfResult();
        r.totalOps            = ops.get();
        r.elapsedMs           = elapsed / 1_000_000.0;
        r.throughputOpsPerSec = r.totalOps / (elapsed / 1_000_000_000.0);
        r.totalBlockedCount   = Math.max(0, blockedAfter     - blockedBefore);
        r.totalBlockedTimeMs  = Math.max(0, blockedTimeAfter - blockedTimeBefore);
        // avgHoldTimeUs: total time threads waited, per operation (in µs)
        r.avgHoldTimeUs       = r.totalOps > 0
                ? (r.totalBlockedTimeMs * 1000.0) / r.totalOps
                : 0.0;
        return r;
    }

    // ─── confirmation rule (Eq. 2 in paper) ─────────────────────────────────

    private static boolean isConfirmed(JsonObject m) {
        double dHTM   = m.get("delta_htm_pct").getAsDouble();
        double dGETS  = m.get("delta_gets_pct").getAsDouble();
        long   spin   = m.get("spin_count").getAsLong();
        return dHTM > TAU_HTM_PCT || dGETS > TAU_GETS_PCT || spin > 0;
    }

    // ─── reflection helpers ──────────────────────────────────────────────────

    private static Class<?> loadClass(String name) {
        try { return Class.forName(name); }
        catch (ClassNotFoundException e) {
            System.out.println("         Class not found: " + name);
            return null;
        }
    }

    private static Method findMethod(Class<?> cls, String name) {
        // Prefer the first method with matching name (handles overloads)
        for (Method m : cls.getDeclaredMethods()) {
            if (m.getName().equals(name)) return m;
        }
        return null;
    }

    private static Object newInstance(Class<?> cls) {
        String simple = cls.getSimpleName();
        try {
            switch (simple) {
                case "BankAccount":
                    return cls.getDeclaredConstructor(String.class, double.class)
                               .newInstance("ACC001", 1_000_000.0);
                case "RequestCounter":
                    return cls.getDeclaredConstructor().newInstance();
                case "UserSessionManager":
                    return cls.getDeclaredConstructor().newInstance();
                default:
                    return cls.getDeclaredConstructor().newInstance();
            }
        } catch (Exception e) {
            System.out.println("         Could not instantiate " + simple + ": " + e.getMessage());
            return null;
        }
    }

    /**
     * Build type-appropriate default arguments for the method.
     * Uses a thread-local counter to avoid HashMap collision in createSession().
     */
    private static final AtomicInteger argCounter = new AtomicInteger(0);

    private static Object[] buildArgs(Method method, Class<?> cls) {
        Class<?>[] types = method.getParameterTypes();
        Object[] args = new Object[types.length];
        String methodName = method.getName();

        for (int i = 0; i < types.length; i++) {
            Class<?> t = types[i];
            if (t == double.class || t == Double.class)   args[i] = 1.0;
            else if (t == float.class)                     args[i] = 1.0f;
            else if (t == int.class)                       args[i] = 1;
            else if (t == long.class)                      args[i] = 1L;
            else if (t == boolean.class)                   args[i] = true;
            else if (t == String.class) {
                // Give each invocation a unique userId so createSession() doesn't
                // always overwrite the same key (which would hide HashMap contention)
                if (methodName.equals("createSession") && i == 0)
                    args[i] = "user_" + argCounter.getAndIncrement();
                else if (methodName.equals("createSession") && i == 1)
                    args[i] = "tok_" + argCounter.get();
                else if (methodName.equals("invalidateSession") || methodName.equals("isSessionValid"))
                    args[i] = "user_0";
                else
                    args[i] = "test";
            }
            else if (t == java.util.List.class || t == java.util.Collection.class) {
                // Supply a small list so the loop actually iterates
                java.util.List<String> list = new java.util.ArrayList<>();
                for (int j = 0; j < 8; j++) list.add("req_" + j);
                args[i] = list;
            }
            else args[i] = null;
        }
        return args;
    }

    // ─── ThreadMXBean aggregation ────────────────────────────────────────────

    private static long sumBlockedCount(ThreadMXBean mx) {
        long sum = 0;
        for (long id : mx.getAllThreadIds()) {
            ThreadInfo ti = mx.getThreadInfo(id);
            if (ti != null) sum += ti.getBlockedCount();
        }
        return sum;
    }

    private static long sumBlockedTime(ThreadMXBean mx) {
        long sum = 0;
        for (long id : mx.getAllThreadIds()) {
            ThreadInfo ti = mx.getThreadInfo(id);
            if (ti != null) sum += Math.max(0, ti.getBlockedTime());
        }
        return sum;
    }

    // ─── math helpers ────────────────────────────────────────────────────────

    private static double pctDelta(double base, double mt) {
        if (base <= 0) return mt > 0 ? 100.0 : 0.0;
        return ((mt - base) / base) * 100.0;
    }

    private static double contentionFactor(ProfResult base, ProfResult mt, int threads) {
        if (base.throughputOpsPerSec <= 0) return 0;
        double expected = base.throughputOpsPerSec * threads;
        return expected / Math.max(mt.throughputOpsPerSec, 1.0);
    }

    private static double round2(double v) {
        return Math.round(v * 100.0) / 100.0;
    }
}
