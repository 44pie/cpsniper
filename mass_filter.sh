#!/bin/bash
#
# mass_filter.sh - Auto-split and filter 3.8M+ domains
#

set -e

# ════════════════════════════════════════════════════════════
#  CONFIGURATION
# ════════════════════════════════════════════════════════════
INPUT_FILE="${1:-woo_domains.txt}"
OUTPUT_DIR="filtered_results"
SPLIT_SIZE=100000  # Domains per part
PARALLEL_JOBS=8    # Number of parallel filter processes

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# ════════════════════════════════════════════════════════════
#  FUNCTIONS
# ════════════════════════════════════════════════════════════
banner() {
    echo -e "${CYAN}"
    echo "   ██████╗██████╗  █████╗ ███╗  ██╗███████╗██╗"
    echo "  ██╔════╝██╔══██╗██╔══██╗████╗ ██║██╔════╝██║"
    echo "  ██║     ██████╔╝███████║██╔██╗██║█████╗  ██║"
    echo "  ██║     ██╔═══╝ ██╔══██║██║╚████║██╔══╝  ██║"
    echo "  ╚██████╗██║     ██║  ██║██║ ╚███║███████╗███████╗"
    echo "   ╚═════╝╚═╝     ╚═╝  ╚═╝╚═╝  ╚══╝╚══════╝╚══════╝"
    echo -e "${NC}"
    echo -e "${CYAN}  MASS TARGET FILTERER${NC}"
    echo -e "${YELLOW}  Auto-split & filter 3.8M+ domains${NC}"
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

check_input() {
    if [ ! -f "$INPUT_FILE" ]; then
        log ERROR "Input file not found: $INPUT_FILE"
        echo ""
        echo "Usage: $0 <domains_file> [output_dir]"
        echo ""
        exit 1
    fi

    local total=$(wc -l < "$INPUT_FILE")
    log INFO "Input file: $INPUT_FILE"
    log INFO "Total domains: $total"
    echo ""
}

split_file() {
    log INFO "Splitting $INPUT_FILE into parts ($SPLIT_SIZE domains each)..."

    local total=$(wc -l < "$INPUT_FILE")
    local parts=$(( (total + SPLIT_SIZE - 1) / SPLIT_SIZE ))
    
    # Create parts directory
    local parts_dir="parts_$(date +%s)"
    mkdir -p "$parts_dir"

    # Split the file
    split -l "$SPLIT_SIZE" -d -a 3 "$INPUT_FILE" "$parts_dir/part_"

    log SUCCESS "Created $parts parts in $parts_dir"
    
    # List parts
    ls -1 "$parts_dir/part_"* > "$parts_dir/parts_list.txt"
    
    echo "$parts_dir"
}

filter_parallel() {
    local parts_dir=$1
    local parts_list="$parts_dir/parts_list.txt"
    
    mkdir -p "$OUTPUT_DIR"
    
    log INFO "Starting parallel filtering ($PARALLEL_JOBS jobs)..."
    log INFO "Output directory: $OUTPUT_DIR"
    echo ""

    local job_count=0
    while IFS= read -r part_file; do
        local part_name=$(basename "$part_file")
        local output_file="$OUTPUT_DIR/${part_name#part_}_filtered.txt"
        local log_file="$OUTPUT_DIR/${part_name#part_}_filtered.log"
        
        ((job_count++))
        
        if [ $job_count -le $PARALLEL_JOBS ]; then
            log INFO "Starting job $job_count/$PARALLEL_JOBS: $part_name"
            nohup bash -c "cd '$PWD' && ./cPanelVulnFinder.sh '$part_file' '$output_file'" > "$log_file" 2>&1 &
            sleep 1  # Small delay between starts
        fi
    done < "$parts_list"

    log SUCCESS "Started $PARALLEL_JOBS parallel filter jobs"
    echo ""
    echo -e "${YELLOW}Running in background...${NC}"
    echo -e "${YELLOW}Check progress: tail -f $OUTPUT_DIR/*.log${NC}"
    echo ""
}

monitor_progress() {
    local parts_dir=$1
    
    echo -e "${CYAN}Press Ctrl+C to stop monitoring${NC}"
    echo ""

    local total_processed=0
    local total_found=0
    
    while true; do
        total_processed=0
        total_found=0
        local job_count=0
        
        for log_file in "$OUTPUT_DIR"/*.log; do
            if [ -f "$log_file" ]; then
                local processed=$(grep -oE 'Normalized [0-9]+ targets' "$log_file" 2>/dev/null | tail -1 | grep -oE '[0-9]+' || echo 0)
                local found=$(grep -oE 'Detected [0-9]+ cPanel/WHM targets' "$log_file" 2>/dev/null | tail -1 | grep -oE '[0-9]+' || echo 0)
                
                total_processed=$((total_processed + processed))
                total_found=$((total_found + found))
                ((job_count++))
            fi
        done
        
        local input_total=$(wc -l < "$INPUT_FILE")
        local progress=$((total_processed * 100 / input_total))
        
        clear
        echo -e "${CYAN}═════════════════════════════════════════════════════════════${NC}"
        echo -e "${CYAN}                    MASS FILTER PROGRESS${NC}"
        echo -e "${CYAN}═════════════════════════════════════════════════════════════${NC}"
        echo ""
        echo -e "${BLUE}Input File:${NC}     $INPUT_FILE"
        echo -e "${BLUE}Total Domains:${NC}  $(printf "'%d" "$input_total")"
        echo ""
        echo -e "${GREEN}Processed:${NC}      $(printf "'%d" "$total_processed") ($progress%)"
        echo -e "${GREEN}Found cPanel:${NC}    $(printf "'%d" "$total_found")"
        echo ""
        echo -e "${YELLOW}Active Jobs:${NC}     $job_count"
        echo -e "${YELLOW}Output Dir:${NC}     $OUTPUT_DIR"
        echo ""
        
        if [ $total_processed -gt 0 ]; then
            local elapsed=0
            for log_file in "$OUTPUT_DIR"/*.log; do
                if [ -f "$log_file" ]; then
                    local file_time=$(stat -c %Y "$log_file" 2>/dev/null || echo 0)
                    [ $file_time -gt $elapsed ] && elapsed=$file_time
                fi
            done
            
            if [ $elapsed -gt 0 ]; then
                local current=$(date +%s)
                local diff=$((current - elapsed))
                if [ $diff -gt 0 ]; then
                    local rate=$((total_processed / diff))
                    local remaining=$(( (input_total - total_processed) / rate))
                    
                    echo -e "${BLUE}Speed:${NC}           $(printf "'%d" "$rate") domains/sec"
                    echo -e "${BLUE}Estimated:${NC}      $((remaining / 60)) minutes"
                fi
            fi
        fi
        
        echo ""
        echo -e "${CYAN}═════════════════════════════════════════════════════════════${NC}"
        echo ""
        echo -e "${CYAN}Press Ctrl+C to stop${NC}"
        echo ""
        
        sleep 5
    done
}

merge_results() {
    log INFO "Merging all filtered results..."
    
    > "$OUTPUT_DIR/all_vulnerable_targets.txt"
    local count=0
    
    for result_file in "$OUTPUT_DIR"/*_filtered.txt; do
        if [ -f "$result_file" ]; then
            cat "$result_file" >> "$OUTPUT_DIR/all_vulnerable_targets.txt"
        fi
    done
    
    # Remove duplicates
    sort -u "$OUTPUT_DIR/all_vulnerable_targets.txt" -o "$OUTPUT_DIR/all_vulnerable_targets.txt"
    
    local final_count=$(wc -l < "$OUTPUT_DIR/all_vulnerable_targets.txt")
    local input_total=$(wc -l < "$INPUT_FILE")
    local reduction=$((final_count * 100 / input_total))
    
    log SUCCESS "Merged $final_count unique targets"
    log SUCCESS "Reduction: ${reduction}% (from $input_total)"
    log SUCCESS "Output: $OUTPUT_DIR/all_vulnerable_targets.txt"
    echo ""
    
    echo -e "${GREEN}[✓] Ready for cPanelSniper:${NC}"
    echo "  cd '$PWD'"
    echo "  python3 cPanelSniper.py -l $OUTPUT_DIR/all_vulnerable_targets.txt -t 50 -o results.json --resume"
    echo ""
}

# ════════════════════════════════════════════════════════════
#  MAIN
# ════════════════════════════════════════════════════════════
main() {
    banner
    
    check_input
    
    # Check dependencies
    if ! command -v cPanelVulnFinder.sh &> /dev/null; then
        log ERROR "cPanelVulnFinder.sh not found in current directory"
        exit 1
    fi
    
    # Split file
    local parts_dir=$(split_file)
    echo ""
    
    # Start parallel filtering
    filter_parallel "$parts_dir"
    
    # Monitor progress
    monitor_progress "$parts_dir"
}

# Run
main "$@"
