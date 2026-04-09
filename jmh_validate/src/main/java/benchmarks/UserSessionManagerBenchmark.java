package benchmarks;

import org.openjdk.jmh.annotations.*;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * JMH benchmark for UserSessionManager — Overly Split + Unified Locking smells.
 *
 * createSession() acquires sessionLock TWICE per call (overly split).
 * All five public methods share the same sessionLock (unified locking), so
 * even unrelated operations (audit log vs session map) serialize against each other.
 *
 * To prevent HashMap unbounded growth during the benchmark, user IDs rotate
 * over a fixed pool of 1 000 keys using an AtomicInteger counter.
 */
@BenchmarkMode(Mode.Throughput)
@OutputTimeUnit(TimeUnit.SECONDS)
@State(Scope.Benchmark)  // single shared UserSessionManager — all threads contend on sessionLock
@Warmup(iterations = 5, time = 1, timeUnit = TimeUnit.SECONDS)
@Measurement(iterations = 10, time = 1, timeUnit = TimeUnit.SECONDS)
@Fork(1)
public class UserSessionManagerBenchmark {

    private static final int POOL_SIZE = 1_000;
    private static final String[] USER_IDS = new String[POOL_SIZE];
    static {
        for (int i = 0; i < POOL_SIZE; i++) USER_IDS[i] = "user_" + i;
    }

    private UserSessionManager manager;
    private final AtomicInteger idGen = new AtomicInteger(0);

    @Setup(Level.Trial)
    public void setup() {
        manager = new UserSessionManager();
        // Pre-populate so invalidateSession has sessions to remove.
        for (String uid : USER_IDS) {
            manager.createSession(uid, "init_token");
        }
    }

    // ── createSession (overly_split + unified_locking) ───────────────────────

    @Benchmark
    @Threads(1)
    public void createSessionBaseline() {
        int idx = idGen.getAndIncrement() % POOL_SIZE;
        manager.createSession(USER_IDS[idx], "tok_" + idx);
    }

    /**
     * 20 threads call createSession() concurrently.
     * Each call acquires sessionLock TWICE — wasted overhead from overly-split smell.
     * Additionally, threads calling invalidateSession or getAuditLog serialize against
     * createSession even though they touch different data (unified locking smell).
     */
    @Benchmark
    @Threads(20)
    public void createSessionStressed() {
        int idx = idGen.getAndIncrement() % POOL_SIZE;
        manager.createSession(USER_IDS[idx], "tok_" + idx);
    }
}
