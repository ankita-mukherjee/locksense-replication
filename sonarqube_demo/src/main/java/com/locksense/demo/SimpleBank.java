package com.locksense.demo;

/**
 * CASE A – Simple synchronized method.
 *
 * SonarQube WILL flag this with rule S2445 / S1999 depending on version.
 * LockSense also detects it (smell: synchronized_method).
 *
 * Purpose in demo: prove SonarQube works on the easy case – then show
 * it fails on the harder cases below.
 */
public class SimpleBank {

    private double balance;

    // SonarQube S2445 / synchronized-method rule WILL flag this.
    public synchronized void deposit(double amount) {
        if (amount <= 0) throw new IllegalArgumentException("Amount must be positive");
        // Simulate some extra work inside the lock (bad practice)
        double tax = amount * 0.01;
        double net = amount - tax;
        this.balance += net;
        System.out.println("Deposited " + net + ", balance=" + this.balance);
    }

    public synchronized double getBalance() {
        return this.balance;
    }
}
