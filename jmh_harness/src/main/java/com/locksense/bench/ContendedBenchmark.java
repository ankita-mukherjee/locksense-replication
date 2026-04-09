package com.locksense.bench;

import org.openjdk.jmh.annotations.*;
import org.openjdk.jmh.runner.Runner;
import org.openjdk.jmh.runner.options.Options;
import org.openjdk.jmh.runner.options.OptionsBuilder;

import java.util.concurrent.TimeUnit;

/**
 * LockSense Job 2 — JMH Benchmark Harness
 *
 * Template used by job2_jmh_runner.py to generate per-candidate benchmarks.
 * Two benchmark modes are instantiated for each candidate method:
 *   B1 — @Threads(1)  : uncontended baseline throughput
 *   B8 — @Threads(8)  : stressed multi-thread throughput
 *
 * Contention Factor (CF) = (T1 × 8) / T8
 * Candidate confirmed if CF > 1.05 AND Mann-Whitney U p < 0.05
 *
 * Parameters fixed globally in .locksense.yml:
 *   warmup=5, measurement=10, forks=1, mode=thrpt
 */
@BenchmarkMode(Mode.Throughput)
@OutputTimeUnit(TimeUnit.SECONDS)
@State(Scope.Benchmark)            // shared state: all threads compete on same object
@Warmup(iterations = 5, time = 1, timeUnit = TimeUnit.SECONDS)
@Measurement(iterations = 10, time = 1, timeUnit = TimeUnit.SECONDS)
@Fork(value = 1)
public class ContendedBenchmark {

    // Shared object — injected by job2_jmh_runner.py per candidate
    private Object sharedTarget;

    @Setup(Level.Trial)
    public void setUp() {
        // job2_jmh_runner.py replaces this with candidate class instantiation
        sharedTarget = new Object();
    }

    /**
     * Baseline: single-thread uncontended throughput (B1).
     * Executed with @Threads(1).
     */
    @Benchmark
    @Threads(1)
    public Object baseline() throws Exception {
        // job2_jmh_runner.py injects: return candidateMethod(sharedTarget, ...)
        return sharedTarget;
    }

    /**
     * Stress: 8-thread contended throughput (B8).
     * All 8 threads share the same @State(Scope.Benchmark) instance.
     */
    @Benchmark
    @Threads(8)
    public Object stressed() throws Exception {
        // job2_jmh_runner.py injects: return candidateMethod(sharedTarget, ...)
        return sharedTarget;
    }

    public static void main(String[] args) throws Exception {
        Options opts = new OptionsBuilder()
                .include(ContendedBenchmark.class.getSimpleName())
                .resultFormat(org.openjdk.jmh.results.format.ResultFormatType.JSON)
                .result("jmh_result.json")
                .build();
        new Runner(opts).run();
    }
}
