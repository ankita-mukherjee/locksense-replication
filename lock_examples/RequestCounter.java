/**
 * EXAMPLE 2: RequestCounter.java
 * ================================
 * SMELL: Loop Outside Critical Section
 *
 * What is wrong:
 *   processRequests() loops over a list of requests. Inside
 *   each loop iteration it acquires the lock, does one small
 *   update, then releases the lock.
 *
 *   With 100 threads each looping 10 times, that is 1000
 *   lock acquire/release cycles per second per thread.
 *   Every acquire/release is a point of contention.
 *
 *   The fix is to acquire the lock ONCE before the loop,
 *   do all the work, then release it once after the loop.
 *
 * What you will see in Job 2:
 *   DELTA_GETS will be very high because acquisitions
 *   multiply by (thread_count × loop_iterations).
 *   SPIN_COUNT will also be non-zero as threads queue up.
 *
 * What Job 3 will suggest:
 *   Move the synchronized block OUTSIDE the loop so the
 *   lock is acquired once per method call, not once per
 *   iteration.
 */
public class RequestCounter {

    private final Object counterLock = new Object();
    private int totalRequests = 0;
    private int successCount = 0;
    private int failureCount = 0;

    /**
     * Process a batch of requests.
     * SMELL: lock acquired and released on EVERY iteration.
     */
    public void processRequests(java.util.List<String> requests) {
        for (String request : requests) {

            // Lock acquired here — every single iteration
            synchronized (counterLock) {
                totalRequests++;

                if (request != null && !request.isEmpty()) {
                    successCount++;
                } else {
                    failureCount++;
                }
            }
            // Lock released here — then immediately re-acquired next iteration
        }
    }

    /**
     * Also smell: synchronized block inside a loop in a different method.
     * Each status check acquires the lock separately.
     */
    public void auditRequests(java.util.List<String> requests) {
        java.util.List<String> failedRequests = new java.util.ArrayList<>();

        for (String req : requests) {
            // Acquiring the lock for every single item just to read
            synchronized (counterLock) {
                if (req == null || req.isEmpty()) {
                    failedRequests.add(req);
                    failureCount++;
                }
            }
        }
    }

    public int getTotalRequests() {
        synchronized (counterLock) {
            return totalRequests;
        }
    }

    public int getSuccessCount() {
        synchronized (counterLock) {
            return successCount;
        }
    }

    public int getFailureCount() {
        synchronized (counterLock) {
            return failureCount;
        }
    }
}
