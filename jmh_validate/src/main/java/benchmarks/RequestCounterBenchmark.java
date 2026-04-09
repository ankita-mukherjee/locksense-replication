package benchmarks;

import org.openjdk.jmh.annotations.*;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.TimeUnit;

/**
 * JMH benchmark for RequestCounter — Loop Outside Critical Section smell.
 *
 * processRequests() acquires and releases the lock on EVERY loop iteration.
 * With 20 threads each looping over 10 items, that is 200 lock acquire/release
 * cycles per "call" — every cycle is a contention point.
 *
 * auditRequests() has the same pattern but only enters the sync block when
 * the request is null or empty — we include empty strings to ensure the body
 * executes and contention is measurable.
 */
@BenchmarkMode(Mode.Throughput)
@OutputTimeUnit(TimeUnit.SECONDS)
@State(Scope.Benchmark)  // single shared RequestCounter — all threads contend on counterLock
@Warmup(iterations = 5, time = 1, timeUnit = TimeUnit.SECONDS)
@Measurement(iterations = 10, time = 1, timeUnit = TimeUnit.SECONDS)
@Fork(1)
public class RequestCounterBenchmark {

    private RequestCounter counter;
    // Mix of empty and non-empty strings so auditRequests() body always executes.
    private List<String> requests;

    @Setup(Level.Trial)
    public void setup() {
        counter = new RequestCounter();
        requests = Collections.unmodifiableList(
            Arrays.asList("r1", "", "r2", "", "r3", "", "r4", "", "r5", "")
        );
    }

    // ── processRequests ───────────────────────────────────────────────────────

    @Benchmark
    @Threads(1)
    public void processRequestsBaseline() {
        counter.processRequests(requests);
    }

    /**
     * 20 threads each call processRequests() concurrently.
     * Each call acquires counterLock 10 times (once per list item).
     * Total lock acquisitions per second = 20 threads × ops/s × 10 items.
     * High ΔGETS expected.
     */
    @Benchmark
    @Threads(20)
    public void processRequestsStressed() {
        counter.processRequests(requests);
    }

    // ── auditRequests ─────────────────────────────────────────────────────────

    @Benchmark
    @Threads(1)
    public void auditRequestsBaseline() {
        counter.auditRequests(requests);
    }

    @Benchmark
    @Threads(20)
    public void auditRequestsStressed() {
        counter.auditRequests(requests);
    }
}
