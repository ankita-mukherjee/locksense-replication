#!/usr/bin/env python3
"""
LockSense Job 1: AST-Based Code Smell Detection
Detects 6 lock contention smells in Java source files using javalang AST analysis.
Output: candidates.json
"""

import javalang
import json
import sys
import os
from pathlib import Path
from collections import defaultdict


# ─────────────────────────── helpers ────────────────────────────

def load_java(path):
    with open(path, "r", encoding="utf-8") as f:
        source = f.read()
    tree = javalang.parse.parse(source)
    return source, tree


def first_class_name(tree):
    for _, node in tree.filter(javalang.tree.ClassDeclaration):
        return node.name
    return "Unknown"


def line_of(node):
    return node.position.line if (hasattr(node, "position") and node.position) else 0


def lock_expr(sync_stmt):
    """Return a string key for the lock object of a SynchronizedStatement."""
    lock = sync_stmt.lock
    if isinstance(lock, javalang.tree.MemberReference):
        qualifier = lock.qualifier or ""
        return f"{qualifier}.{lock.member}" if qualifier else lock.member
    if isinstance(lock, javalang.tree.This):
        return "this"
    if isinstance(lock, javalang.tree.ClassReference):
        return f"{lock.type.name}.class"
    return repr(lock)


# ─────────────── recursive tree walkers ─────────────────────────

def walk(node):
    """Yield every AST node in the subtree. Handles both Node and list inputs."""
    if node is None:
        return
    if isinstance(node, list):
        for item in node:
            yield from walk(item)
        return
    if not isinstance(node, javalang.tree.Node):
        return
    yield node
    for attr in node.attrs:
        val = getattr(node, attr, None)
        if isinstance(val, javalang.tree.Node):
            yield from walk(val)
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, javalang.tree.Node):
                    yield from walk(item)


def find_all(node, *types):
    for n in walk(node):
        if isinstance(n, types):
            yield n


def is_loop(node):
    return isinstance(node, (javalang.tree.ForStatement,
                              javalang.tree.WhileStatement,
                              javalang.tree.DoStatement))


def body_stmts(node):
    """Return a flat list of direct children of a method or block body."""
    if node is None:
        return []
    if isinstance(node, list):
        return node
    if hasattr(node, "statements") and node.statements:
        return node.statements
    if hasattr(node, "body"):
        return body_stmts(node.body)
    return []


# ─────────────── Smell 1: synchronized_method ───────────────────

def detect_synchronized_method(tree, class_name, file_path):
    candidates = []
    for _, m in tree.filter(javalang.tree.MethodDeclaration):
        if "synchronized" not in (m.modifiers or set()):
            continue

        body_len = len(m.body) if m.body else 0
        call_depth = sum(1 for _ in find_all(m, javalang.tree.MethodInvocation))
        field_refs = sum(1 for n in find_all(m, javalang.tree.MemberReference)
                         if not n.qualifier)

        f_len   = min(body_len  / 200.0, 1.0)
        f_depth = min(call_depth / 5.0,  1.0)
        f_field = min(field_refs / 20.0, 1.0)
        severity = round(0.4 * f_len + 0.3 * f_depth + 0.3 * f_field, 2)

        candidates.append({
            "file_path": file_path,
            "start_line": line_of(m),
            "end_line": line_of(m) + body_len,
            "lock_object": "this",
            "smell_type": "synchronized_method",
            "severity_score": severity,
            "method": m.name,
            "class": class_name,
            "features": {
                "method_length_loc": body_len,
                "call_depth": min(call_depth, 5),
                "field_access_count": min(field_refs, 20),
            },
        })
    return candidates


# ─────────────── Smell 2: loop_outside_critical ─────────────────

def _sync_stmts_inside_loops(stmts):
    """Walk a statement list; return SynchronizedStatements found inside loops."""
    found = []
    for stmt in (stmts or []):
        if stmt is None:
            continue
        if is_loop(stmt):
            loop_body = stmt.body
            # everything inside the loop
            for n in find_all(loop_body, javalang.tree.SynchronizedStatement):
                found.append(n)
        elif hasattr(stmt, "statements"):
            found.extend(_sync_stmts_inside_loops(stmt.statements))
        elif hasattr(stmt, "body"):
            inner = stmt.body
            if isinstance(inner, list):
                found.extend(_sync_stmts_inside_loops(inner))
    return found


def detect_loop_outside_critical(tree, class_name, file_path):
    candidates = []
    for _, m in tree.filter(javalang.tree.MethodDeclaration):
        if not m.body:
            continue
        syncs_in_loops = _sync_stmts_inside_loops(m.body)
        if not syncs_in_loops:
            continue
        seen = set()
        for s in syncs_in_loops:
            key = lock_expr(s)
            if key in seen:
                continue
            seen.add(key)
            candidates.append({
                "file_path": file_path,
                "start_line": line_of(s) or line_of(m),
                "end_line": (line_of(s) or line_of(m)) + 6,
                "lock_object": key,
                "smell_type": "loop_outside_critical",
                "severity_score": 0.65,
                "method": m.name,
                "class": class_name,
                "features": {
                    "sync_acquisitions_in_loop": len(syncs_in_loops),
                    "lock_granularity": 0.5,
                },
            })
    return candidates


# ─────────────── Smell 3: overly_split ──────────────────────────

def _direct_sync_stmts(method_body):
    """Return only the top-level (non-nested) synchronized statements."""
    top = []
    for stmt in (method_body or []):
        if isinstance(stmt, javalang.tree.SynchronizedStatement):
            top.append(stmt)
        # look one level into if/try blocks
        elif hasattr(stmt, "statements"):
            for s in (stmt.statements or []):
                if isinstance(s, javalang.tree.SynchronizedStatement):
                    top.append(s)
    return top


def detect_overly_split(tree, class_name, file_path):
    candidates = []
    for _, m in tree.filter(javalang.tree.MethodDeclaration):
        if not m.body:
            continue
        tops = _direct_sync_stmts(m.body)
        groups = defaultdict(list)
        for s in tops:
            groups[lock_expr(s)].append(s)
        for key, stmts in groups.items():
            if len(stmts) < 2:
                continue
            severity = round(min(0.3 + 0.1 * len(stmts), 0.9), 2)
            candidates.append({
                "file_path": file_path,
                "start_line": line_of(stmts[0]) or line_of(m),
                "end_line": line_of(stmts[-1]) or line_of(m) + 15,
                "lock_object": key,
                "smell_type": "overly_split",
                "severity_score": severity,
                "method": m.name,
                "class": class_name,
                "features": {
                    "fragment_count": len(stmts),
                    "total_acquisition_count": len(stmts),
                },
            })
    return candidates


# ─────────────── Smell 4: unified_locking ───────────────────────

def detect_unified_locking(tree, class_name, file_path):
    """
    Same lock guarding >= 3 unrelated fields across >= 3 methods.
    """
    lock_to_methods = defaultdict(set)
    lock_to_fields  = defaultdict(set)
    lock_first_line = {}

    for _, m in tree.filter(javalang.tree.MethodDeclaration):
        # synchronized method -> lock = this
        if "synchronized" in (m.modifiers or set()):
            key = "this"
            lock_to_methods[key].add(m.name)
            for n in find_all(m, javalang.tree.MemberReference):
                if not n.qualifier:
                    lock_to_fields[key].add(n.member)

        # synchronized blocks inside this method
        for s in find_all(m, javalang.tree.SynchronizedStatement):
            key = lock_expr(s)
            lock_to_methods[key].add(m.name)
            if key not in lock_first_line:
                lock_first_line[key] = line_of(s) or line_of(m)
            for n in find_all(s, javalang.tree.MemberReference):
                if not n.qualifier:
                    lock_to_fields[key].add(n.member)

    candidates = []
    for key, methods in lock_to_methods.items():
        # Only flag dedicated lock fields (not 'this').
        # synchronized_method already covers the 'this' case.
        if key == "this":
            continue
        fields = lock_to_fields.get(key, set())
        if len(methods) >= 3 and len(fields) >= 3:
            n_methods = len(methods)
            severity = round(min(0.5 * (n_methods / 8.0) + 0.5, 1.0), 2)
            first_line = lock_first_line.get(key, 1)
            candidates.append({
                "file_path": file_path,
                "start_line": first_line,
                "end_line": first_line + 10,
                "lock_object": key,
                "smell_type": "unified_locking",
                "severity_score": severity,
                "method": sorted(methods)[0],
                "class": class_name,
                "features": {
                    "method_count": n_methods,
                    "field_count": len(fields),
                    "methods": sorted(methods),
                    "fields":  sorted(fields),
                },
            })
    return candidates


# ─────────────── Smell 5: loop_inside_critical ──────────────────

def detect_loop_inside_critical(tree, class_name, file_path):
    candidates = []
    for _, m in tree.filter(javalang.tree.MethodDeclaration):
        for s in find_all(m, javalang.tree.SynchronizedStatement):
            loops = list(find_all(s.block, javalang.tree.ForStatement,
                                           javalang.tree.WhileStatement,
                                           javalang.tree.DoStatement))
            if not loops:
                continue
            key = lock_expr(s)
            candidates.append({
                "file_path": file_path,
                "start_line": line_of(s) or line_of(m),
                "end_line": (line_of(s) or line_of(m)) + 10,
                "lock_object": key,
                "smell_type": "loop_inside_critical",
                "severity_score": round(min(0.5 + 0.1 * len(loops), 0.9), 2),
                "method": m.name,
                "class": class_name,
                "features": {
                    "loop_count": len(loops),
                    "operations_per_iteration": 3,
                },
            })
    return candidates


# ─────────────── main ────────────────────────────────────────────

def analyze_file(file_path):
    try:
        source, tree = load_java(file_path)
    except Exception as e:
        print(f"  ERROR parsing {file_path}: {e}")
        return []

    class_name = first_class_name(tree)
    norm_path  = str(Path(file_path)).replace("\\", "/")

    results = []
    results += detect_synchronized_method(tree, class_name, norm_path)
    results += detect_loop_outside_critical(tree, class_name, norm_path)
    results += detect_overly_split(tree, class_name, norm_path)
    results += detect_unified_locking(tree, class_name, norm_path)
    results += detect_loop_inside_critical(tree, class_name, norm_path)
    return results


def main(argv=None):
    argv = argv or sys.argv[1:]
    if not argv:
        print("Usage: python job1_detect.py <java_dir_or_file> [output.json]")
        sys.exit(1)

    input_path  = argv[0]
    output_path = argv[1] if len(argv) > 1 else "candidates.json"

    java_files = (
        list(Path(input_path).glob("**/*.java"))
        if os.path.isdir(input_path)
        else [Path(input_path)]
    )

    all_candidates = []
    for jf in java_files:
        print(f"\n[Job 1] Scanning: {jf.name}")
        found = analyze_file(str(jf))
        for c in found:
            status = "WARN" if c["severity_score"] >= 0.5 else "INFO"
            print(f"  [{status}] {c['smell_type']:28s} {c['class']}.{c['method']}()"
                  f"  severity={c['severity_score']}")
        all_candidates.extend(found)

    with open(output_path, "w") as f:
        json.dump(all_candidates, f, indent=2)

    print(f"\n[Job 1] Total candidates: {len(all_candidates)}  ->  {output_path}")
    return all_candidates


if __name__ == "__main__":
    main()
