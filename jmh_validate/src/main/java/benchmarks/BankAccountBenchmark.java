package benchmarks;

import org.openjdk.jmh.annotations.*;
import java.util.concurrent.TimeUnit;

/**
 * JMH benchmark for BankAccount — Synchronized Method smell.
 *
 * Each smelly method has two variants:
 *   *Baseline  @Threads(1)  — contention-free reference throughput
 *   *Stressed  @Threads(20) — concurrent load that reveals lock contention
 *
 * The Job 2 Python parser maps these benchmark names to candidate records
 * by stripping "Benchmark" from the class name and "Baseline"/"Stressed"
 * from the method name.
 *
 * Expected result: deposit/withdraw will show extreme contention factor
 * (>10x) because Thread.sleep(5 ms) holds the lock while all other
 * threads wait. getBalance() may show moderate contention.
 */
@BenchmarkMode(Mode.Throughput)
@OutputTimeUnit(TimeUnit.SECONDS)
@State(Scope.Benchmark)   // one shared BankAccount — all threads contend on 'this'
@Warmup(iterations = 5, time = 1, timeUnit = TimeUnit.SECONDS)
@Measurement(iterations = 10, time = 1, timeUnit = TimeUnit.SECONDS)
@Fork(1)
public class BankAccountBenchmark {

    private BankAccount account;

    @Setup(Level.Trial)
    public void setup() {
        // Large balance so withdraw() never exhausts funds.
        // At ~200 ops/s (serialised by 5 ms sleep) over 15 s → 3 000 withdrawals.
        account = new BankAccount("ACC001", 1_000_000_000.0);
    }

    // ── deposit ──────────────────────────────────────────────────────────────

    @Benchmark
    @Threads(1)
    public void depositBaseline() {
        account.deposit(1.0);
    }

    /**
     * 20 threads call deposit() concurrently.
     * deposit() sleeps 5 ms while holding the lock → all other threads queue.
     * Ideal throughput = 200 ops/s × 20 = 4 000 ops/s.
     * Actual throughput ≈ 200 ops/s → contention_factor ≈ 20x.
     */
    @Benchmark
    @Threads(20)
    public void depositStressed() {
        account.deposit(1.0);
    }

    // ── withdraw ─────────────────────────────────────────────────────────────

    @Benchmark
    @Threads(1)
    public void withdrawBaseline() {
        try {
            account.withdraw(1.0);
        } catch (IllegalArgumentException ignored) {}
    }

    @Benchmark
    @Threads(20)
    public void withdrawStressed() {
        try {
            account.withdraw(1.0);
        } catch (IllegalArgumentException ignored) {}
    }

    // ── getBalance ───────────────────────────────────────────────────────────

    @Benchmark
    @Threads(1)
    public double getBalanceBaseline() {
        return account.getBalance();
    }

    @Benchmark
    @Threads(20)
    public double getBalanceStressed() {
        return account.getBalance();
    }
}
