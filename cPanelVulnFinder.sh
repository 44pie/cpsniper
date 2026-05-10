#!/bin/bash
#
# cPanelVulnFinder.sh - Find potentially vulnerable cPanel targets for CVE-2026-41940
# Usage: ./cPanelVulnFinder.sh <input_file> [output_file]
#

set -e

# ══════════════════════════════════════════════════════════════
#  CONFIGURATION
# ══════════════════════════════════════════════════════════════
INPUT_FILE="${1:-targets.txt}"
OUTPUT_FILE="${2:-vulnerable_targets.txt}"
TEMP_DIR=$(mktemp -d)
THREADS=50
TIMEOUT=5
VERBOSE=${VERBOSE:-0}

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# ══════════════════════════════════════════════════════════════
#  FUNCTIONS
# ══════════════════════════════════════════════════════════════
banner() {
    echo -e "${CYAN}"
    echo "   ██████╗██████╗  █████╗ ███╗  ██╗███████╗██╗"
    echo "  ██╔════╝██╔══██╗██╔══██╗████╗ ██║██╔════╝██║"
    echo "  ██║     ██████╔╝███████║██╔██╗██║█████╗  ██║"
    echo "  ██║     ██╔═══╝ ██╔══██║██║╚████║██╔══╝  ██║"
    echo "  ╚██████╗██║     ██║  ██║██║ ╚███║███████╗███████╗"
    echo "   ╚═════╝╚═╝     ╚═╝  ╚═╝╚═╝  ╚══╝╚══════╝╚══════╝"
    echo -e "${NC}"
    echo -e "${CYAN}  CVE-2026-41940 Target Finder${NC}"
    echo -e "${YELLOW}  Identify potentially vulnerable cPanel/WHM servers${NC}"
    echo ""
}

log() {
    local level=$1
    shift
    local msg="$@"
    local timestamp=$(date '+%H:%M:%S')

    case $level in
        INFO)  echo -e "${BLUE}[$timestamp] [INFO]${NC} $msg" ;;
        WARN)  echo -e "${YELLOW}[$timestamp] [WARN]${NC} $msg" ;;
        SUCCESS) echo -e "${GREEN}[$timestamp] [✓]${NC} $msg" ;;
        ERROR) echo -e "${RED}[$timestamp] [✗]${NC} $msg" ;;
        *)     echo "[$timestamp] [$level] $msg" ;;
    esac
}

check_dependencies() {
    log INFO "Checking dependencies..."

    if ! command -v curl &> /dev/null; then
        log ERROR "curl is required but not installed"
        exit 1
    fi

    if ! command -v httpx &> /dev/null; then
        log ERROR "httpx is required. Install: go install -v github.com/projectdiscovery/httpx/cmd/httpx@latest"
        exit 1
    fi

    log SUCCESS "All dependencies found"
}

normalize_targets() {
    local input=$1
    local output=$2

    log INFO "Normalizing targets and adding default ports..."

    while IFS= read -r line; do
        # Skip empty lines and comments
        [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue

        # Extract domain/IP
        target=$(echo "$line" | grep -oE '^[^[:space:]]+' || echo "$line")

        # Add protocol if missing
        [[ ! "$target" =~ ^https?:// ]] && target="https://$target"

        # Add port if missing
        if [[ ! "$target" =~ :[0-9]+$ ]]; then
            target="${target}:2087"
        fi

        echo "$target"
    done < "$input" | sort -u > "$output"

    local count=$(wc -l < "$output")
    log SUCCESS "Normalized $count targets"
}

check_alive() {
    local input=$1
    local output=$2

    log INFO "Checking alive status (HTTP $THREADS threads)..."

    httpx -silent -status-code -timeout "$TIMEOUT" -threads "$THREADS" \
        -H "User-Agent: Mozilla/5.0" < "$input" | \
        grep -E "200|301|302|307|401|403|500" | \
        awk '{print $1}' | sort -u > "$output"

    local count=$(wc -l < "$output")
    log SUCCESS "Found $count alive targets"
}

detect_cpanel() {
    local input=$1
    local output=$2

    log INFO "Detecting cPanel/WHM services..."

    > "$output"

    local count=0
    local found=0
    while IFS= read -r target; do
        ((count++))
        [ $VERBOSE -eq 1 ] && log INFO "[$count] Checking: $target"

        # Get response headers
        headers=$(curl -sI -m "$TIMEOUT" --connect-timeout 3 "$target" 2>/dev/null | head -15)

        # Check for cPanel/WHM indicators
        is_cpanel=0

        # Check headers
        if echo "$headers" | grep -qiE "cpanel|cpsrvd|whostmgr"; then
            is_cpanel=1
        fi

        if [ $is_cpanel -eq 1 ]; then
            ((found++))
            echo "$target" >> "$output"
        fi

    done < "$input"

    local count=$(wc -l < "$output" 2>/dev/null || echo 0)
    log SUCCESS "Detected $count cPanel/WHM targets"
}

extract_version() {
    local input=$1
    local output="$2"  # Use quotes to avoid issues with empty paths

    # Check if input file exists and is not empty
    if [ ! -f "$input" ] || [ ! -s "$input" ]; then
        log INFO "No cPanel targets found, skipping version extraction"
        # Create empty output files if they don't exist
        [ -n "$output" ] && > "$output"
        > "$TEMP_DIR/version_details.txt"
        return
    fi

    log INFO "Extracting cPanel versions..."

    > "$output"
    > "$TEMP_DIR/version_details.txt"

    local count=0
    local with_version=0

    while IFS= read -r target; do
        ((count++))
        [ $VERBOSE -eq 1 ] && log INFO "[$count] Version check: $target"

        # Try to get version from /json-api/version
        version=$(curl -s -m "$TIMEOUT" --connect-timeout 3 \
            "$target/json-api/version" 2>/dev/null | \
            grep -oP '"version":\s*"\K[^"]+' || echo "")

        if [ -n "$version" ]; then
            ((with_version++))
            # Determine if vulnerable
            major=$(echo "$version" | cut -d. -f2)
            minor=$(echo "$version" | cut -d. -f3)
            patch=$(echo "$version" | cut -d. -f4)

            case "$major" in
                110) limit=97 ;;
                118) limit=63 ;;
                126) limit=54 ;;
                132) limit=29 ;;
                134) limit=20 ;;
                136) limit=5 ;;
                *) limit=999 ;;
            esac

            if [ "$major" -ge 110 ] && [ "$major" -le 136 ] 2>/dev/null; then
                if [ -n "$patch" ] && [ "$patch" -lt "$limit" ] 2>/dev/null; then
                    status="VULNERABLE"
                elif [ -n "$patch" ] && [ "$patch" -ge "$limit" ] 2>/dev/null; then
                    status="PATCHED"
                else
                    status="CHECK"
                fi
            else
                status="UNKNOWN"
            fi

            echo "$target|$version|$status" >> "$TEMP_DIR/version_details.txt"
        fi
    done < "$input"

    log SUCCESS "Extracted version for $with_version targets"
}

filter_vulnerable() {
    local input=$1
    local version_file=$2
    local output="$3"  # Use quotes

    log INFO "Filtering vulnerable targets..."

    > "$output"
    > "$TEMP_DIR/vulnerable.txt"
    > "$TEMP_DIR/unknown.txt"

    # Check if we have versioned targets
    local has_version=0
    if [ -f "$TEMP_DIR/version_details.txt" ] && [ -s "$TEMP_DIR/version_details.txt" ]; then
        while IFS='|' read -r target version status; do
            if [ "$status" = "VULNERABLE" ]; then
                echo "$target" >> "$output"
                echo "$target" >> "$TEMP_DIR/vulnerable.txt"
            elif [ "$status" = "CHECK" ] || [ "$status" = "UNKNOWN" ]; then
                echo "$target" >> "$output"
                echo "$target" >> "$TEMP_DIR/unknown.txt"
            fi
        done < "$TEMP_DIR/version_details.txt"
        has_version=1
    fi

    # If no versions extracted, add all cPanel targets as unknown
    if [ $has_version -eq 0 ] && [ -f "$input" ] && [ -s "$input" ]; then
        while IFS= read -r target; do
            echo "$target" >> "$output"
            echo "$target" >> "$TEMP_DIR/unknown.txt"
        done < "$input"
    fi

    local vulnerable=$(wc -l < "$TEMP_DIR/vulnerable.txt" 2>/dev/null || echo 0)
    local unknown=$(wc -l < "$TEMP_DIR/unknown.txt" 2>/dev/null || echo 0)
    local total=$(wc -l < "$output")

    log SUCCESS "Found $vulnerable vulnerable, $unknown unknown versions"
    log SUCCESS "Total: $total targets for cPanelSniper"
}

cleanup() {
    log INFO "Cleaning up temporary files..."
    rm -rf "$TEMP_DIR"
}

print_summary() {
    local output=$1

    echo ""
    echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "${CYAN}                        SUMMARY${NC}"
    echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
    echo ""

    # Vulnerable targets
    if [ -f "$TEMP_DIR/vulnerable.txt" ]; then
        local count=$(wc -l < "$TEMP_DIR/vulnerable.txt" 2>/dev/null || echo 0)
        if [ $count -gt 0 ]; then
            echo -e "${GREEN}[VULNERABLE]${NC} High-confidence vulnerable targets:"
            cat "$TEMP_DIR/vulnerable.txt"
        fi
    fi

    # Unknown versions (need scan)
    if [ -f "$TEMP_DIR/unknown.txt" ]; then
        local count=$(wc -l < "$TEMP_DIR/unknown.txt" 2>/dev/null || echo 0)
        if [ $count -gt 0 ]; then
            echo ""
            echo -e "${YELLOW}[UNKNOWN]${NC} Targets with unknown versions (need full scan):"
            head -10 "$TEMP_DIR/unknown.txt"
            [ $count -gt 10 ] && echo -e "${YELLOW}... and $((count-10)) more${NC}"
        fi
    fi

    echo ""
    echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
    echo ""
    echo -e "${GREEN}[✓] Output saved to: ${output}${NC}"
    echo ""
    echo -e "${CYAN}Usage with cPanelSniper:${NC}"
    echo "  cd /path/to/cpsniper"
    echo "  python3 cPanelSniper.py -l $output -t 50 -o results.json"
    echo ""
}

# ══════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════
main() {
    banner

    # Parse arguments
    if [ -n "$1" ] && [ -f "$1" ]; then
        INPUT_FILE="$1"
    elif [ -n "$1" ]; then
        INPUT_FILE="$1"
    fi

    if [ -n "$2" ]; then
        OUTPUT_FILE="$2"
    fi

    # Check input file
    if [ ! -f "$INPUT_FILE" ]; then
        log ERROR "Input file not found: $INPUT_FILE"
        echo ""
        echo "Usage: $0 <input_file> [output_file]"
        echo "  input_file  - File with domains/IPs (one per line)"
        echo "  output_file - Output file for cPanelSniper (default: vulnerable_targets.txt)"
        echo ""
        exit 1
    fi

    log INFO "Input file: $INPUT_FILE"
    log INFO "Output file: $OUTPUT_FILE"
    log INFO "Threads: $THREADS"
    log INFO "Timeout: ${TIMEOUT}s"
    echo ""

    # Check dependencies
    check_dependencies
    echo ""

    # Pipeline
    local stage1="$TEMP_DIR/stage1_normalized.txt"
    local stage2="$TEMP_DIR/stage2_alive.txt"
    local stage3="$TEMP_DIR/stage3_cpanel.txt"

    normalize_targets "$INPUT_FILE" "$stage1"
    check_alive "$stage1" "$stage2"
    detect_cpanel "$stage2" "$stage3"
    extract_version "$stage3" "$stage4"
    filter_vulnerable "$stage3" "$stage4" "$OUTPUT_FILE"

    # Print summary
    print_summary "$OUTPUT_FILE"

    # Cleanup
    cleanup

    log SUCCESS "Done!"
    exit 0
}

# Trap cleanup on exit
trap cleanup EXIT

# Run main if script is executed directly (not sourced)
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
