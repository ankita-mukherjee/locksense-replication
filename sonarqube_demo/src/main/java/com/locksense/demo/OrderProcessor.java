package com.locksense.demo;

import java.util.ArrayList;
import java.util.List;

/**
 * CASE C – Loop Inside Critical Section smell (complex case).
 *
 * The synchronized block wraps a potentially-long loop over a list
 * of orders. Every other thread is blocked for the ENTIRE duration
 * of the loop, even though the shared state (processedCount) only
 * needs to be updated once after the loop completes.
 *
 * Why SonarQube MISSES this:
 *   - S2925 flags Thread.sleep() inside a lock – but there is no sleep here.
 *   - No SonarQube rule tracks loop iteration count or loop body cost
 *     relative to lock hold time.
 *   - SonarQube cannot model the performance impact of holding a lock
 *     across N iterations of a loop.
 *
 * LockSense detects it as: loop_inside_critical
 * (loop found inside a synchronized block -> high contention risk)
 *
 * ALSO demonstrates: loop_outside_critical (acquireLockPerItem method):
 *   The lock is acquired and released inside the loop – O(N) acquisitions
 *   instead of O(1).  SonarQube has no rule for this either.
 */
public class OrderProcessor {

    private final Object lock = new Object();
    private int processedCount = 0;

    /** Smell: loop_inside_critical – long work inside the lock. */
    public void processOrders(List<String> orders) {
        synchronized (lock) {                      // lock acquired ONCE ...
            for (String order : orders) {          // ... held for ALL N orders
                // Simulate per-order processing (CPU + I/O bound in production)
                String upper = order.toUpperCase();
                System.out.println("Processing: " + upper);
            }
            processedCount += orders.size();       // only this line needs the lock
        }
    }

    /** Smell: loop_outside_critical – lock acquired once PER item (O(N) acquires). */
    public void acquireLockPerItem(List<String> orders) {
        for (String order : orders) {
            synchronized (lock) {                  // acquired and released N times
                processedCount++;
                System.out.println("Logged: " + order);
            }
        }
    }

    public int getProcessedCount() {
        synchronized (lock) {
            return processedCount;
        }
    }
}
