/**
 * EXAMPLE 1: BankAccount.java
 * ===========================
 * SMELL: Synchronized Method
 *
 * What is wrong:
 *   Both deposit() and withdraw() are declared synchronized.
 *   This means the ENTIRE method body is locked on 'this'.
 *   When 100 threads call deposit() and withdraw() at the same
 *   time, every single thread must wait for every other thread
 *   to finish completely — even the Thread.sleep(5) that
 *   simulates a slow database write inside the lock.
 *
 * What you will see in Job 2:
 *   DELTA_HTM will be very high (thousands of percent) because
 *   each thread holds the lock while sleeping — all other
 *   threads spin-wait the entire time.
 *
 * What Job 3 will suggest:
 *   Remove synchronized from the method signature.
 *   Use a synchronized block around ONLY the balance update,
 *   not the database write.
 */
public class BankAccount {

    private double balance;
    private String accountId;
    private String lastTransactionLog;

    public BankAccount(String accountId, double initialBalance) {
        this.accountId = accountId;
        this.balance = initialBalance;
    }

    // SMELL: entire method is locked including the slow DB write
    public synchronized void deposit(double amount) {

        // Step 1: validate (does not need the lock)
        if (amount <= 0) {
            throw new IllegalArgumentException("Amount must be positive");
        }

        // Step 2: slow external write — simulates database log
        // This holds the lock for 5ms while ALL other threads wait
        try {
            Thread.sleep(5);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }

        // Step 3: actual shared-state update (this DOES need the lock)
        this.balance += amount;
        this.lastTransactionLog = "DEPOSIT " + amount + " -> balance: " + this.balance;
    }

    // SMELL: second synchronized method — same lock, same problem
    public synchronized void withdraw(double amount) {

        if (amount <= 0 || amount > this.balance) {
            throw new IllegalArgumentException("Invalid withdrawal amount");
        }

        // Slow external write holds the lock unnecessarily
        try {
            Thread.sleep(5);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }

        this.balance -= amount;
        this.lastTransactionLog = "WITHDRAW " + amount + " -> balance: " + this.balance;
    }

    // SMELL: third synchronized method — any read also blocks everyone
    public synchronized double getBalance() {
        return this.balance;
    }

    public String getAccountId() {
        return accountId;
    }
}
