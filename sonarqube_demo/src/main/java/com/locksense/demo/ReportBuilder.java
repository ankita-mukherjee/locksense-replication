package com.locksense.demo;

import java.util.ArrayList;
import java.util.List;

/**
 * CASE D – Overly Split synchronized blocks (complex case).
 *
 * The same lock is acquired and released TWICE inside one method, with
 * only non-shared work between them.  This causes two lock round-trips
 * where one would suffice, and also creates a visibility gap between the
 * two critical sections that can expose partially-updated state.
 *
 * Why SonarQube MISSES this:
 *   - No SonarQube rule detects multiple synchronized blocks on the SAME
 *     lock object within a single method.
 *   - S2445 fires only when the lock expression is a non-final local or
 *     parameter; 'this' and final fields are exempt.
 *   - SonarQube performs no intra-method control-flow analysis for lock
 *     pairing or lock-release-reacquire patterns.
 *
 * LockSense detects it as: overly_split
 * (>= 2 synchronized blocks on the same lock in one method)
 */
public class ReportBuilder {

    private final List<String> headerLines  = new ArrayList<>();
    private final List<String> dataLines    = new ArrayList<>();
    private int                reportVersion = 0;

    /**
     * Builds a report section: acquires lock twice on 'this' in one method.
     * The CPU-bound formatting between the two blocks holds no shared state,
     * yet both critical sections pay the overhead of a separate lock round-trip.
     */
    public void buildSection(String title, List<String> rawData) {

        // --- First critical section: update header ---
        synchronized (this) {
            reportVersion++;
            headerLines.add("[v" + reportVersion + "] " + title);
        }

        // Non-shared work (could run freely without any lock)
        List<String> formatted = new ArrayList<>();
        for (String row : rawData) {
            formatted.add(row.trim().toUpperCase());
        }

        // --- Second critical section (same lock): update data ---
        synchronized (this) {                   // second acquisition unnecessary
            dataLines.addAll(formatted);
        }
    }

    public synchronized List<String> getReport() {
        List<String> report = new ArrayList<>(headerLines);
        report.addAll(dataLines);
        return report;
    }
}
