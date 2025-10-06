#!/bin/bash
#PBS -S /bin/bash
#PBS -l nodes=1:ppn=%nthread/%cluster_server_directive/
#PBS -q %queue_directive/
#PBS -N %jobname/
#PBS -j eo
#PBS -m ae
#PBS -e %logpath/

## Check command ##
if [ -e "$HOME/.bashrc" ]; then
    source "$HOME/.bashrc"
fi
if [ -e "$HOME/.zshrc" ]; then
    zsh "$HOME/.zshrc"
fi
commands=("cellranger")
for command in "${commands[@]}"; do
    if command -v "$command" >/dev/null 2>&1; then
        echo "[CHECK] $command: Resolved."
    else
        echo "[CHECK] $command: Could not resolve."
        exit 1
    fi
done
##################

##Functions#######
get_median_length() {
    zcat "$1" | awk '{if(NR%4==2) {print length($0)}}' | sort -n | awk '{
        count++; length_sum+=$1; length_array[count]=$1
    } END {
        if(count%2) {
            print length_array[int(count/2)+1]
        } else {
            print (length_array[count/2]+length_array[count/2+1])/2
        }
    }'
}
###################
filetype="%filetype/"
sample_id="%sample_id/"

mkdir -p "%download_target/" && cd "%download_target/"

if [ "$filetype" = "bam" ]; then
    if [ ! -f "$sample_id.bam" ]; then
        wget "%download_source/" -O "$sample_id.bam"
    fi

    if [ -d "fastqs" ]; then
        rm -rf "./fastqs"
    fi
    cellranger bamtofastq --nthreads=%nthread/ "$sample_id.bam" "./fastqs"
    find "./fastqs" -type f -name "bamtofastq_*.fastq.gz" | while read file; do
        base_name=$(basename "$file" | sed 's/bamtofastq_//')
        dir_name=$(dirname "$file")
        new_file_name="${sample_id}_${base_name}"
        mv "$file" "$dir_name/$new_file_name"
    done

elif [ "$filetype" = "fastq" ]; then
    parent_dir="$(pwd)/fastqs"
    if [ ! -d "fastqs" ]; then
        mkdir -p "fastqs"
        cd "fastqs"
    fi
    IFS=',' read -ra run_ids <<<"%run_ids_str/"
    for run_id in "${run_ids[@]}"; do
        cd "$parent_dir"
        mkdir -p "$run_id"
        cd "$run_id"

        echo "[INFO] Downloading $run_id..."
        fastq-dump --split-files --origfmt --gzip "$run_id"

        # Count FASTQ files
        input_fastqs=($(ls ${run_id}*.fastq.gz 2>/dev/null))
        num_files=${#input_fastqs[@]}

        if [ $num_files -eq 0 ]; then
            echo "[WARNING] No FASTQ files found for $run_id, skipping..."
            continue
        fi

        echo "[INFO] Found $num_files FASTQ file(s) for $run_id"

        if [ $num_files -eq 2 ]; then
            # Use Python auto-detection for R1/R2
            echo "[INFO] Auto-detecting R1/R2 orientation..."

            # Get Celline Python module path
            CELLINE_PYTHON="${CELLINE_PYTHON:-python3}"
            CELLINE_DETECT="${CELLINE_ROOT:-/path/to/celline}/src/celline/utils/fastq_detect.py"

            # Try to find fastq_detect.py
            if [ ! -f "$CELLINE_DETECT" ]; then
                # Fallback: try to find it via Python import
                CELLINE_DETECT=$($CELLINE_PYTHON -c "import celline.utils.fastq_detect as m; print(m.__file__)" 2>/dev/null || echo "")
            fi

            if [ -f "$CELLINE_DETECT" ]; then
                # Use Python auto-detection
                $CELLINE_PYTHON "$CELLINE_DETECT" \
                    "${input_fastqs[0]}" \
                    "${input_fastqs[1]}" \
                    --sample "$sample_id" \
                    --lane L001

                if [ $? -eq 0 ]; then
                    echo "[SUCCESS] R1/R2 auto-detection completed"
                else
                    echo "[WARNING] Auto-detection failed, falling back to length-based method"
                    # Fallback to old method
                    use_length_fallback=1
                fi
            else
                echo "[WARNING] fastq_detect.py not found, using length-based fallback"
                use_length_fallback=1
            fi

            # Length-based fallback
            if [ "${use_length_fallback:-0}" -eq 1 ]; then
                echo "[INFO] Using length-based R1/R2 detection..."

                # Sort files by median length
                declare -a sorted_files=()
                for file in "${input_fastqs[@]}"; do
                    median_length=$(get_median_length "$file")
                    sorted_files+=("$median_length $file")
                done

                # Sort by length and extract files
                sorted_files=($(printf '%s\n' "${sorted_files[@]}" | sort -n))

                # Extract file names (shorter = R1, longer = R2)
                r1_file=$(echo "${sorted_files[0]}" | cut -d' ' -f2-)
                r2_file=$(echo "${sorted_files[1]}" | cut -d' ' -f2-)

                # Rename
                mv "$r1_file" "${sample_id}_S1_L001_R1_001.fastq.gz"
                mv "$r2_file" "${sample_id}_S1_L001_R2_001.fastq.gz"

                echo "[INFO] Renamed: $r1_file -> ${sample_id}_S1_L001_R1_001.fastq.gz"
                echo "[INFO] Renamed: $r2_file -> ${sample_id}_S1_L001_R2_001.fastq.gz"
            fi

        elif [ $num_files -eq 3 ]; then
            # 3 files: R1, R2, I1
            # Expected lengths: I1 (~8bp) < R1 (~26-28bp) < R2 (~50-150bp)
            echo "[INFO] Detected 3 files, identifying R1, R2, I1..."

            # Store file->length mapping to avoid key collision
            declare -A file_to_length
            for file in "${input_fastqs[@]}"; do
                median_length=$(get_median_length "$file")
                file_to_length["$file"]=$median_length
                echo "[DEBUG] $file: median_length=$median_length"
            done

            # Classify each file by length range
            i1_file=""
            r1_file=""
            r2_file=""

            for file in "${input_fastqs[@]}"; do
                len=${file_to_length[$file]}

                if [ "$len" -le 12 ]; then
                    # Index read (I1)
                    i1_file="$file"
                    echo "[DEBUG] Classified as I1 (${len}bp): $file"
                elif [ "$len" -ge 24 ] && [ "$len" -le 30 ]; then
                    # R1 (barcode)
                    r1_file="$file"
                    echo "[DEBUG] Classified as R1 (${len}bp): $file"
                elif [ "$len" -ge 40 ]; then
                    # R2 (cDNA)
                    r2_file="$file"
                    echo "[DEBUG] Classified as R2 (${len}bp): $file"
                else
                    echo "[WARNING] Ambiguous length $len for $file"
                fi
            done

            # Fallback if classification incomplete
            if [ -z "$i1_file" ] || [ -z "$r1_file" ] || [ -z "$r2_file" ]; then
                echo "[WARNING] Classification incomplete, using length-based fallback"
                # Sort files by length
                sorted_files=($(for f in "${input_fastqs[@]}"; do echo "${file_to_length[$f]} $f"; done | sort -n | awk '{print $2}'))
                i1_file="${sorted_files[0]}"
                r1_file="${sorted_files[1]}"
                r2_file="${sorted_files[2]}"
            fi

            mv "$r1_file" "${sample_id}_S1_L001_R1_001.fastq.gz"
            mv "$r2_file" "${sample_id}_S1_L001_R2_001.fastq.gz"
            mv "$i1_file" "${sample_id}_S1_L001_I1_001.fastq.gz"

            echo "[INFO] Assigned: I1=$i1_file, R1=$r1_file, R2=$r2_file"

        elif [ $num_files -eq 4 ]; then
            # 4 files: R1, R2, I1, I2
            # Expected lengths: I1 (~8bp) ≈ I2 (~8bp) < R1 (~26-28bp) < R2 (~50-150bp)
            echo "[INFO] Detected 4 files, identifying R1, R2, I1, I2..."

            # Store file->length mapping to avoid key collision
            declare -A file_to_length
            for file in "${input_fastqs[@]}"; do
                median_length=$(get_median_length "$file")
                file_to_length["$file"]=$median_length
                echo "[DEBUG] $file: median_length=$median_length"
            done

            # Classify each file by length range
            declare -a index_files=()
            r1_file=""
            r2_file=""

            for file in "${input_fastqs[@]}"; do
                len=${file_to_length[$file]}

                if [ "$len" -le 12 ]; then
                    # Index read (I1 or I2)
                    index_files+=("$file")
                    echo "[DEBUG] Classified as index (${len}bp): $file"
                elif [ "$len" -ge 24 ] && [ "$len" -le 30 ]; then
                    # R1 (barcode)
                    r1_file="$file"
                    echo "[DEBUG] Classified as R1 (${len}bp): $file"
                elif [ "$len" -ge 40 ]; then
                    # R2 (cDNA)
                    r2_file="$file"
                    echo "[DEBUG] Classified as R2 (${len}bp): $file"
                else
                    echo "[WARNING] Ambiguous length $len for $file"
                fi
            done

            # Assign index files
            if [ ${#index_files[@]} -ge 2 ]; then
                i1_file="${index_files[0]}"
                i2_file="${index_files[1]}"
            elif [ ${#index_files[@]} -eq 1 ]; then
                i1_file="${index_files[0]}"
                i2_file=""
            fi

            # Fallback if classification incomplete
            if [ -z "$r1_file" ] || [ -z "$r2_file" ] || [ ${#index_files[@]} -eq 0 ]; then
                echo "[WARNING] Classification incomplete, using length-based fallback"
                # Sort files by length
                sorted_files=($(for f in "${input_fastqs[@]}"; do echo "${file_to_length[$f]} $f"; done | sort -n | awk '{print $2}'))
                i1_file="${sorted_files[0]}"
                i2_file="${sorted_files[1]}"
                r1_file="${sorted_files[2]}"
                r2_file="${sorted_files[3]}"
            fi

            # Rename files
            [ -n "$r1_file" ] && mv "$r1_file" "${sample_id}_S1_L001_R1_001.fastq.gz"
            [ -n "$r2_file" ] && mv "$r2_file" "${sample_id}_S1_L001_R2_001.fastq.gz"
            [ -n "$i1_file" ] && mv "$i1_file" "${sample_id}_S1_L001_I1_001.fastq.gz"
            [ -n "$i2_file" ] && mv "$i2_file" "${sample_id}_S1_L001_I2_001.fastq.gz"

            echo "[INFO] Assigned: I1=$i1_file, I2=$i2_file, R1=$r1_file, R2=$r2_file"
        else
            echo "[WARNING] Unexpected number of files: $num_files"
        fi
    done
else
    echo "[ERROR] Input should be 'bam' or 'fastqs'"
    exit 1
fi
