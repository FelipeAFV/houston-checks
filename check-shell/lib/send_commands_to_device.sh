#!/bin/bash
# ==========================================
# Ephemeral Network Device SSH Runner Engine
# ==========================================

TARGET_USER="$1"
TARGET_HOST="$2"
TARGET_PORT="${3:-22}"
TARGET_PASSWORD="$4"
SESSION_TIMEOUT="${SSH_PTY_TIMEOUT:-120}"
STEP_TIMEOUT="${SSH_PTY_STEP_TIMEOUT:-45}"

if [ -z "$TARGET_USER" ] || [ -z "$TARGET_HOST" ]; then
    echo "Usage: $0 <user> <host> [port] [password]" >&2
    exit 1
fi

CONTENT=$(cat)
if [ -z "$CONTENT" ]; then
    echo "Error: No commands received via stdin." >&2
    exit 1
fi

# Inherit parent session ID for persistence, or fallback to local unique identifier
SESSION_NAME="${SESSION_ID:-session_${$}_${RANDOM}}"
SESSION_DEADLINE=$((SECONDS + SESSION_TIMEOUT))

PREV_OUTPUT_COLOR=""

dump_session() {
    tmux capture-pane -p -J -S - -t "$SESSION_NAME" 2>/dev/null || true
}

fail_session() {
    local msg=$1
    echo "Error: ${msg}" >&2
    dump_session
    tmux kill-session -t "$SESSION_NAME" 2>/dev/null
    exit 1
}

# Ensure resource cleanup on unexpected termination signals
trap 'tmux kill-session -t "$SESSION_NAME" 2>/dev/null' SIGINT SIGTERM

if ! command -v tmux >/dev/null 2>&1; then
    echo "Error: tmux not found (install tmux on bastion)" >&2
    exit 127
fi

if [[ -n "$TARGET_PASSWORD" ]] && ! command -v sshpass >/dev/null 2>&1; then
    echo "Error: sshpass not found (install sshpass on bastion)" >&2
    exit 127
fi

# Tail terminal output until a shell prompt, password request, or timeout occurs
stream_until_prompt() {
    local allow_disconnect="${1:-""}"
    local stable_cycles=0
    local loop_count=0
    local step_deadline=$((SECONDS + STEP_TIMEOUT))

    while (( SECONDS < SESSION_DEADLINE )) && (( SECONDS < step_deadline )); do
        ((loop_count++))

        local current_output_color
        current_output_color=$(tmux capture-pane -ep -J -S - -t "$SESSION_NAME" 2>/dev/null)
        if [ $? -ne 0 ]; then
            if ! tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
                # Differentiate between a safe 'exit' command and an abrupt SSH drop
                if [[ "$allow_disconnect" == "allow_disconnect" ]]; then
                    return 0
                fi
                fail_session "SSH connection closed unexpectedly or failed to establish."
            fi
            break
        fi

        local current_output_plain
        current_output_plain=$(tmux capture-pane -p -J -S - -t "$SESSION_NAME" 2>/dev/null)

        # Intercept standard SSH network/auth errors immediately
        if echo "$current_output_plain" | grep -qiE 'connection (refused|timed out)|no route to host|could not resolve|permission denied|authentication failed'; then
            fail_session "SSH session failed for ${TARGET_USER}@${TARGET_HOST}:${TARGET_PORT}"
        fi

        # Delta tracking: Stream only new characters added since the last iteration
        local len_curr=${#current_output_color}
        local len_prev=${#PREV_OUTPUT_COLOR}

        if [ "$current_output_color" != "$PREV_OUTPUT_COLOR" ]; then
            if [ "$len_curr" -ge "$len_prev" ]; then
                printf "%s" "${current_output_color:$len_prev}"
            else
                printf "%s" "$current_output_color"
            fi
            PREV_OUTPUT_COLOR="$current_output_color"
            stable_cycles=0
        else
            ((stable_cycles++))
        fi

        # Parse the screen layout once the terminal stream output stabilizes
        if [ $stable_cycles -ge 15 ]; then
            local last_line
            last_line=$(echo "$current_output_plain" | grep '[a-zA-Z0-9]' | tail -n 1 | tr -cd '\11\12\15\40-\176' | sed 's/[[:space:]]*$//')
            local last_char="${last_line: -1}"

            # Handle interactive mid-session or initial password challenges
            if [[ -n "$TARGET_PASSWORD" ]] && { [[ "${last_line,,}" == *password:* ]] || [[ "$last_char" == "?" ]]; }; then
                tmux send-keys -t "$SESSION_NAME" "$TARGET_PASSWORD" C-m
                stable_cycles=0
                PREV_OUTPUT_COLOR=""
                sleep 0.3
                continue
            fi

            # Match standard network OS prompt indicators ($, #, >, %, :)
            if [[ "$last_char" == "$" || "$last_char" == "#" || "$last_char" == ">" || "$last_char" == "%" || "$last_char" == ":" ]]; then
                if [[ "${last_line,,}" != *password:* ]] && [[ "$last_char" != "?" ]]; then
                    return 0
                fi
            fi
        fi
        sleep 0.01
    done

    fail_session "timed out waiting for device prompt (${TARGET_USER}@${TARGET_HOST}:${TARGET_PORT})"
}

# ==============================================================================
# Session Orchestration Layer
# ==============================================================================
if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
    # Re-use existing terminal context and snapshot current screen as baseline
    PREV_OUTPUT_COLOR=$(tmux capture-pane -ep -J -S - -t "$SESSION_NAME" 2>/dev/null)
else
    # Initialize a new detached tmux session wrapping the SSH lifecycle
    ssh_common="-tt -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=15 -o ServerAliveInterval=10 -o ServerAliveCountMax=3 -o LogLevel=ERROR -p $(printf '%q' "$TARGET_PORT") $(printf '%q' "${TARGET_USER}@${TARGET_HOST}")"

    if [[ -n "$TARGET_PASSWORD" ]]; then
        tmux_cmd="sshpass -p $(printf '%q' "$TARGET_PASSWORD") ssh ${ssh_common}"
    else
        tmux_cmd="ssh ${ssh_common}"
    fi

    if ! tmux new-session -d -x 200 -y 2000 -s "$SESSION_NAME" "$tmux_cmd"; then
        fail_session "failed to start tmux SSH session to ${TARGET_USER}@${TARGET_HOST}:${TARGET_PORT}"
    fi

    sleep 0.5
    stream_until_prompt
fi

# ==============================================================================
# Command Execution Loop
# ==============================================================================
while IFS= read -r cmd || [ -n "$cmd" ]; do
    cmd=$(echo "$cmd" | tr -d '\r' | sed 's/[[:space:]]*$//')
    [[ "$cmd" == \#* ]] || [[ -z "$cmd" ]] && continue

    if ! tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
        fail_session "Session vanished before sending command: $cmd"
    fi

    tmux send-keys -t "$SESSION_NAME" "$cmd" C-m
    
    # Allow graceful terminal destruction exclusively when sending exit sequences
    if [[ "$cmd" == "exit" ]]; then
        stream_until_prompt "allow_disconnect"
    else
        stream_until_prompt
    fi
    
    if ! tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
        exit 0
    fi
done <<< "$CONTENT"

exit 0
