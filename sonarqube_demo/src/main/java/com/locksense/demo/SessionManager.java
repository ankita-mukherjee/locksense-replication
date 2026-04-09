package com.locksense.demo;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * CASE B – Unified Locking smell (complex case).
 *
 * A SINGLE lock object ("sessionLock") guards THREE completely independent
 * data structures: active sessions, an audit log, and a request counter.
 * Any thread touching sessions blocks threads that only need to update the
 * counter, and vice-versa.
 *
 * Why SonarQube MISSES this:
 *   - No rule exists that reasons about lock scope vs. field independence.
 *   - S2445 only flags synchronized(non-final-field); sessionLock IS final.
 *   - S1199 / S2925 target empty sync blocks or Thread.sleep inside locks.
 *   - SonarQube has NO cross-method data-flow analysis for lock objects.
 *
 * LockSense detects it as: unified_locking
 * (same lock -> >= 3 methods, >= 3 unrelated fields)
 */
public class SessionManager {

    // One lock for everything – the contention smell
    private final Object sessionLock = new Object();

    // Three completely independent data structures
    private final Map<String, String> activeSessions = new HashMap<>();
    private final List<String>        auditLog        = new ArrayList<>();
    private int                       requestCounter  = 0;

    /** Add a new user session – touches activeSessions. */
    public void createSession(String userId, String token) {
        synchronized (sessionLock) {
            activeSessions.put(userId, token);
            auditLog.add("CREATE " + userId);
        }
    }

    /** Remove a user session – touches activeSessions. */
    public void removeSession(String userId) {
        synchronized (sessionLock) {
            activeSessions.remove(userId);
            auditLog.add("REMOVE " + userId);
        }
    }

    /** Increment the global request counter – UNRELATED to sessions. */
    public void recordRequest(String endpoint) {
        synchronized (sessionLock) {   // BLOCKS on session ops unnecessarily
            requestCounter++;
            auditLog.add("REQUEST " + endpoint);
        }
    }

    /** Read request count - UNRELATED to sessions. */
    public int getRequestCount() {
        synchronized (sessionLock) {   // CONTENDS with createSession / removeSession
            return requestCounter;
        }
    }

    /** Read audit log - touches auditLog only. */
    public List<String> getAuditLog() {
        synchronized (sessionLock) {   // all 5 methods block each other
            return new ArrayList<>(auditLog);
        }
    }
}
