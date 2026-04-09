/**
 * EXAMPLE 3: UserSessionManager.java
 * =====================================
 * SMELL 1: Unified Locking
 * SMELL 2: Overly Split Locks
 *
 * What is wrong:
 *   A single lock 'sessionLock' guards THREE completely
 *   unrelated things: the sessions map, the audit log list,
 *   and the loginCount counter.
 *
 *   When Thread A is writing to the audit log, Thread B
 *   cannot update the session map — even though those two
 *   things have nothing to do with each other. They share
 *   one lock, so they serialize unnecessarily.
 *
 *   Additionally, createSession() acquires sessionLock
 *   TWICE in the same method (overly split) — once to
 *   add to sessions, once to add to the audit log.
 *   Each acquire/release pair is wasted overhead.
 *
 * What you will see in Job 2:
 *   Both DELTA_HTM and DELTA_GETS will be elevated.
 *   All three operations (session write, audit write,
 *   count update) queue behind each other even though
 *   they are independent.
 *
 * What Job 3 will suggest:
 *   Split into three separate locks — one per resource.
 *   Or replace simple counters with AtomicInteger.
 *   Merge the split lock acquisitions in createSession().
 */
public class UserSessionManager {

    // ONE lock guarding THREE unrelated resources — the smell
    private final Object sessionLock = new Object();

    private java.util.Map<String, String> sessions
            = new java.util.HashMap<>();

    private java.util.List<String> auditLog
            = new java.util.ArrayList<>();

    private int loginCount = 0;

    /**
     * SMELL: Overly Split Locks — sessionLock acquired TWICE.
     * SMELL: Unified Locking — same lock for sessions AND auditLog.
     */
    public void createSession(String userId, String token) {

        // First acquisition — updates sessions map
        synchronized (sessionLock) {
            sessions.put(userId, token);
        }

        // Lock released, then immediately re-acquired for audit log.
        // These two blocks could be merged into one.

        // Second acquisition — writes to audit log
        synchronized (sessionLock) {
            auditLog.add("LOGIN: " + userId + " at " + System.currentTimeMillis());
            loginCount++;
        }
    }

    /**
     * SMELL: Unified Locking — same lock as createSession()
     * even though invalidateSession only touches sessions map.
     * A thread calling invalidateSession blocks createSession
     * and vice versa — even though one only reads sessions
     * and the other only writes auditLog.
     */
    public void invalidateSession(String userId) {
        synchronized (sessionLock) {
            sessions.remove(userId);
            auditLog.add("LOGOUT: " + userId + " at " + System.currentTimeMillis());
        }
    }

    /**
     * SMELL: Unified Locking — audit log has nothing to do
     * with session management but uses the same lock.
     * Any thread reading the audit log blocks all session
     * operations while it holds the lock.
     */
    public java.util.List<String> getAuditLog() {
        synchronized (sessionLock) {
            return new java.util.ArrayList<>(auditLog);
        }
    }

    public boolean isSessionValid(String userId) {
        synchronized (sessionLock) {
            return sessions.containsKey(userId);
        }
    }

    public int getLoginCount() {
        synchronized (sessionLock) {
            return loginCount;
        }
    }
}
