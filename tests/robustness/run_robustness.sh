#!/usr/bin/env bash
# Robustness test: run flake8-stepdown against real-world Python projects.
# Detects crashes (unhandled exceptions) and code corruption (tests broken by fix).
set -uo pipefail

PLUGIN_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WORK_DIR=$(mktemp -d)
PROJECTS_FILE="$SCRIPT_DIR/projects.json"
TEST_TIMEOUT=300

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

log()  { echo -e "${CYAN}[INFO]${NC} $*"; }
ok()   { echo -e "${GREEN}[OK]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
fail() { echo -e "${RED}[FAIL]${NC} $*"; }

# Result accumulators
declare -a RESULTS_NAME=()
declare -a RESULTS_CHECK=()
declare -a RESULTS_VIOLATIONS=()
declare -a RESULTS_FIX=()
declare -a RESULTS_SYNTAX=()
declare -a RESULTS_TESTS_BEFORE=()
declare -a RESULTS_TESTS_AFTER=()
declare -a RESULTS_VERDICT=()

HAS_FAILURE=0

# Parse projects.json with python
read_projects() {
    python3 -c "
import json, sys
with open('$PROJECTS_FILE') as f:
    projects = json.load(f)
for p in projects:
    print(p['name'])
    print(p['repo'])
    print(p['ref'])
    print(p['source_dir'])
    print(p['test_cmd'])
    print(p['install_extras'])
"
}

# Extract pytest summary counts from output
# Returns "X passed, Y failed" or "no tests"
extract_test_summary() {
    local output_file="$1"
    local passed failed errors
    passed=$(grep -oP '\d+(?= passed)' "$output_file" | tail -1 || echo "0")
    failed=$(grep -oP '\d+(?= failed)' "$output_file" | tail -1 || echo "0")
    errors=$(grep -oP '\d+(?= error)' "$output_file" | tail -1 || echo "0")
    passed=${passed:-0}
    failed=${failed:-0}
    errors=${errors:-0}
    local total=$((passed + failed + errors))
    if [ "$total" -eq 0 ]; then
        echo "no tests"
    else
        echo "${passed}p/${failed}f/${errors}e"
    fi
}

extract_failed_count() {
    local output_file="$1"
    local failed
    failed=$(grep -oP '\d+(?= failed)' "$output_file" | tail -1 || echo "0")
    echo "${failed:-0}"
}

# Check if stderr contains a Python traceback
has_traceback() {
    grep -q "Traceback (most recent call last)" "$1" 2>/dev/null
}

process_project() {
    local name="$1" repo="$2" ref="$3" source_dir="$4" test_cmd="$5" install_extras="$6"

    echo ""
    echo -e "${BOLD}════════════════════════════════════════${NC}"
    log "Processing: ${BOLD}$name${NC}"
    echo -e "${BOLD}════════════════════════════════════════${NC}"

    local project_dir="$WORK_DIR/$name"
    local check_ok="SKIP" violations="N/A" fix_ok="SKIP" syntax_ok="SKIP"
    local tests_before="SKIP" tests_after="SKIP" verdict="SKIP"

    # --- Clone ---
    log "Cloning $repo ($ref)..."
    if ! git clone --depth 1 --branch "$ref" "$repo" "$project_dir" 2>&1 | tail -1; then
        fail "Clone failed for $name"
        RESULTS_NAME+=("$name")
        RESULTS_CHECK+=("SKIP"); RESULTS_VIOLATIONS+=("N/A"); RESULTS_FIX+=("SKIP")
        RESULTS_SYNTAX+=("SKIP"); RESULTS_TESTS_BEFORE+=("SKIP"); RESULTS_TESTS_AFTER+=("SKIP")
        RESULTS_VERDICT+=("SKIP")
        return
    fi

    cd "$project_dir" || return

    # --- Setup venv ---
    log "Setting up venv..."
    uv venv .venv --python 3.12 -q 2>&1 | tail -3
    local pip="uv pip install --python .venv/bin/python"

    # Install the project itself
    log "Installing $name..."
    if ! $pip -e ".${install_extras}" -q 2>&1 | tail -3; then
        # Fallback: install non-editable
        $pip ".${install_extras}" -q 2>&1 | tail -3 || true
    fi

    # Install test dependencies (try common extra names)
    log "Installing test dependencies..."
    $pip -e ".[dev]" -q 2>/dev/null \
        || $pip -e ".[test]" -q 2>/dev/null \
        || $pip -e ".[testing]" -q 2>/dev/null \
        || $pip -e ".[tests]" -q 2>/dev/null \
        || true

    # Also try requirements files
    for req in requirements-dev.txt requirements_dev.txt requirements-test.txt; do
        [ -f "$req" ] && $pip -r "$req" -q 2>/dev/null || true
    done

    $pip pytest -q 2>/dev/null || true

    # Install flake8-stepdown from local source
    log "Installing flake8-stepdown..."
    $pip "$PLUGIN_DIR" -q 2>&1 | tail -3

    local venv_python=".venv/bin/python"
    local venv_stepdown=".venv/bin/stepdown"

    if [ ! -f "$venv_stepdown" ]; then
        fail "stepdown not found in venv"
        RESULTS_NAME+=("$name")
        RESULTS_CHECK+=("SKIP"); RESULTS_VIOLATIONS+=("N/A"); RESULTS_FIX+=("SKIP")
        RESULTS_SYNTAX+=("SKIP"); RESULTS_TESTS_BEFORE+=("SKIP"); RESULTS_TESTS_AFTER+=("SKIP")
        RESULTS_VERDICT+=("SKIP")
        return
    fi

    # ================================================================
    # Phase 1: Smoke test - stepdown check
    # ================================================================
    log "Phase 1: stepdown check on $source_dir..."
    local check_stderr
    check_stderr=$(mktemp)
    local check_stdout
    check_stdout=$(mktemp)

    $venv_stepdown check "$source_dir" >"$check_stdout" 2>"$check_stderr"
    local check_exit=$?

    if [ $check_exit -le 1 ] && ! has_traceback "$check_stderr"; then
        check_ok="OK"
        ok "stepdown check completed (exit $check_exit)"
    else
        check_ok="CRASH"
        fail "stepdown check crashed (exit $check_exit)"
        if has_traceback "$check_stderr"; then
            cat "$check_stderr" | head -20
        fi
        HAS_FAILURE=1
    fi

    # Count violations
    violations=$(grep -c "TDP001" "$check_stdout" 2>/dev/null || echo "0")
    log "Violations found: $violations"

    # ================================================================
    # Phase 2: Baseline tests
    # ================================================================
    log "Phase 2a: Running baseline tests..."
    local tests_before_file
    tests_before_file=$(mktemp)

    # shellcheck disable=SC2086  # word splitting intended for test_cmd
    (cd "$project_dir" && timeout "$TEST_TIMEOUT" .venv/bin/$test_cmd) >"$tests_before_file" 2>&1
    local tests_before_exit=$?

    tests_before=$(extract_test_summary "$tests_before_file")
    local failed_before
    failed_before=$(extract_failed_count "$tests_before_file")

    if [ $tests_before_exit -eq 124 ]; then
        tests_before="TIMEOUT"
        warn "Tests timed out after ${TEST_TIMEOUT}s"
    else
        log "Baseline tests: $tests_before (exit $tests_before_exit)"
    fi

    # ================================================================
    # Phase 3: stepdown fix
    # ================================================================
    log "Phase 3: stepdown fix on $source_dir..."
    local fix_stderr
    fix_stderr=$(mktemp)

    $venv_stepdown fix "$source_dir" 2>"$fix_stderr"
    local fix_exit=$?

    if [ $fix_exit -le 1 ] && ! has_traceback "$fix_stderr"; then
        fix_ok="OK"
        ok "stepdown fix completed (exit $fix_exit)"
    else
        fix_ok="CRASH"
        fail "stepdown fix crashed (exit $fix_exit)"
        if has_traceback "$fix_stderr"; then
            cat "$fix_stderr" | head -20
        fi
        HAS_FAILURE=1
    fi

    # ================================================================
    # Phase 4: Syntax check after fix
    # ================================================================
    log "Phase 4: Syntax validation..."
    local syntax_err
    syntax_err=$(mktemp)
    if find "$source_dir" -name "*.py" -exec "$venv_python" -m py_compile {} + 2>"$syntax_err"; then
        syntax_ok="OK"
        ok "All files have valid syntax"
    else
        syntax_ok="FAIL"
        fail "Syntax errors after fix:"
        cat "$syntax_err" | head -10
        HAS_FAILURE=1
    fi

    # ================================================================
    # Phase 5: Post-fix tests
    # ================================================================
    if [ "$tests_before" != "TIMEOUT" ] && [ "$tests_before" != "no tests" ]; then
        log "Phase 5: Running post-fix tests..."
        local tests_after_file
        tests_after_file=$(mktemp)

        # shellcheck disable=SC2086  # word splitting intended for test_cmd
        (cd "$project_dir" && timeout "$TEST_TIMEOUT" .venv/bin/$test_cmd) >"$tests_after_file" 2>&1
        local tests_after_exit=$?

        tests_after=$(extract_test_summary "$tests_after_file")
        local failed_after
        failed_after=$(extract_failed_count "$tests_after_file")

        if [ $tests_after_exit -eq 124 ]; then
            tests_after="TIMEOUT"
            warn "Post-fix tests timed out"
        else
            log "Post-fix tests: $tests_after (exit $tests_after_exit)"
        fi

        # Compare failures
        if [ "$failed_after" -gt "$failed_before" ]; then
            verdict="CORRUPTION"
            fail "Test regressions detected! Before: ${failed_before} failed, After: ${failed_after} failed"
            HAS_FAILURE=1
        elif [ "$syntax_ok" = "FAIL" ]; then
            verdict="CORRUPTION"
        elif [ "$check_ok" = "CRASH" ] || [ "$fix_ok" = "CRASH" ]; then
            verdict="CRASH"
        else
            verdict="OK"
            ok "No regressions"
        fi
    else
        tests_after="SKIP"
        if [ "$check_ok" = "CRASH" ] || [ "$fix_ok" = "CRASH" ]; then
            verdict="CRASH"
        elif [ "$syntax_ok" = "FAIL" ]; then
            verdict="CORRUPTION"
        else
            verdict="OK"
        fi
    fi

    # --- Reset ---
    git checkout -- . 2>/dev/null

    # --- Record ---
    RESULTS_NAME+=("$name")
    RESULTS_CHECK+=("$check_ok")
    RESULTS_VIOLATIONS+=("$violations")
    RESULTS_FIX+=("$fix_ok")
    RESULTS_SYNTAX+=("$syntax_ok")
    RESULTS_TESTS_BEFORE+=("$tests_before")
    RESULTS_TESTS_AFTER+=("$tests_after")
    RESULTS_VERDICT+=("$verdict")
}

print_summary() {
    echo ""
    echo -e "${BOLD}╔══════════════════════════════════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}║                              ROBUSTNESS TEST RESULTS                                       ║${NC}"
    echo -e "${BOLD}╠══════════════════════╦═══════╦════════════╦═══════╦════════╦════════════════╦════════════════╣${NC}"
    printf  "${BOLD}║ %-20s ║ %-5s ║ %-10s ║ %-5s ║ %-6s ║ %-14s ║ %-14s ║${NC}\n" \
        "Project" "Check" "Violations" "Fix" "Syntax" "Tests Before" "Tests After"
    echo -e "${BOLD}╠══════════════════════╬═══════╬════════════╬═══════╬════════╬════════════════╬════════════════╣${NC}"

    local i
    for i in "${!RESULTS_NAME[@]}"; do
        local color="$NC"
        case "${RESULTS_VERDICT[$i]}" in
            OK) color="$GREEN" ;;
            CRASH|CORRUPTION) color="$RED" ;;
            SKIP) color="$YELLOW" ;;
        esac

        printf "${color}║ %-20s ║ %-5s ║ %10s ║ %-5s ║ %-6s ║ %-14s ║ %-14s ║${NC}\n" \
            "${RESULTS_NAME[$i]}" \
            "${RESULTS_CHECK[$i]}" \
            "${RESULTS_VIOLATIONS[$i]}" \
            "${RESULTS_FIX[$i]}" \
            "${RESULTS_SYNTAX[$i]}" \
            "${RESULTS_TESTS_BEFORE[$i]}" \
            "${RESULTS_TESTS_AFTER[$i]}"
    done

    echo -e "${BOLD}╚══════════════════════╩═══════╩════════════╩═══════╩════════╩════════════════╩════════════════╝${NC}"
    echo ""
    echo -e "Work directory: $WORK_DIR"
    echo ""

    if [ "$HAS_FAILURE" -eq 1 ]; then
        fail "Some projects had issues!"
    else
        ok "All projects passed!"
    fi
}

# ================================================================
# Main
# ================================================================
log "Plugin directory: $PLUGIN_DIR"
log "Work directory: $WORK_DIR"
log "Projects config: $PROJECTS_FILE"
echo ""

# Read projects and process them
while IFS= read -r name && \
      IFS= read -r repo && \
      IFS= read -r ref && \
      IFS= read -r source_dir && \
      IFS= read -r test_cmd && \
      IFS= read -r install_extras; do
    process_project "$name" "$repo" "$ref" "$source_dir" "$test_cmd" "$install_extras"
done < <(read_projects)

print_summary

exit "$HAS_FAILURE"
