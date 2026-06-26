# lib/utils.sh

send_commands_to_device() {
    if [[ -z "$TARGET_USER" || -z "$TARGET_HOST" || -z "$TARGET_PORT" ]]; then
        echo "Usage: send_commands_to_device <user> <host> <port> [<password>]" >&2
        return 1
    fi

    SESSION_SHA=`echo ${JOB_EXECID}_${TARGET_USER}_${TARGET_HOST}_${TARGET_HOST} | sha1sum | awk '{print $1}'`
    export SESSION_ID="session_${SESSION_SHA}"

    $SCRIPT_DIR/../lib/send_commands_to_device.sh "$TARGET_USER" "$TARGET_HOST" "$TARGET_PORT" "$TARGET_PASSWORD"
}

make_temp_file() {
    COMMAND_OUTPUT_FILE=$(mktemp /tmp/`basename $0`.output.XXXXXX)
    trap 'rm -f "$COMMAND_OUTPUT_FILE"' EXIT
    echo $COMMAND_OUTPUT_FILE
}

load_expected_values() {
    local target_file="${1:-$SCRIPT_DIR/../expected_values.txt}"

    if [ ! -f "$target_file" ]; then
        echo "Error: File '$target_file' does not exist." >&2
        return 1
    fi

    source <(
        while IFS='=' read -r key val || [ -n "$key" ]; do
            [[ "$key" =~ ^[[:space:]]*# ]] || [[ -z "$(echo "$key" | tr -d '[:space:]')" ]] && continue
            
            clean_key=$(echo "$key" | tr -d '[:space:]')
            clean_val=$(echo "$val" | tr -d '\r')
            
            printf "export expected_%s=\"%s\"\n" "$clean_key" "$clean_val"
        done < "$target_file"
    )
    
    echo "Successfully loaded expected values for checks from: $target_file"
}