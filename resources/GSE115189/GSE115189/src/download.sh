#!/bin/bash
#PBS -S /bin/bash
#PBS -l nodes=1:ppn=1:
#PBS -q 
#PBS -N Download
#PBS -j eo
#PBS -m ae
#PBS -e /Users/yuyasato/Documents/dev/Celline/resources/GSE115189/GSE115189/logs/download_20250602_20:47:18.log

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
    zcat $1 | awk '{if(NR%4==2) {print length($0)}}' | sort -n | awk '{
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
filetype="bam"
sample_id="GSE115189"

mkdir -p "/Users/yuyasato/Documents/dev/Celline/resources/GSE115189/GSE115189/raw" && cd "/Users/yuyasato/Documents/dev/Celline/resources/GSE115189/GSE115189/raw"

if [ "$filetype" = "bam" ]; then
    if [ ! -f "$sample_id.bam" ]; then
        wget "https://sra-pub-src-1.s3.amazonaws.com/SRR7244582/possorted_genome_bam.bam.1" -O "$sample_id.bam"
    fi

    if [ -d "fastqs" ]; then
        rm -rf "./fastqs"
    fi
    cellranger bamtofastq --nthreads=1 "$sample_id.bam" "./fastqs"
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
    IFS=',' read -ra run_ids <<<"SRR7244582"
    for run_id in "${run_ids[@]}"; do
        cd "$parent_dir"
        mkdir -p "$run_id"
        # if the number of file starting with "${sample_id}_S1_L001" and ending with "fastq.gz" is less than 2
        #TODO: ここが上手く動いてません
        # if [ $(ls ${sample_id}_S1_L001*.fastq.gz 2> /dev/null | wc -l) -lt 2 ]; then
        #     # remove recursively
        #     cd ..
        #     rm -rf "$run_id"
        #     continue
        # fi
        cd "$run_id"
        fastq-dump --split-files --origfmt --gzip "$run_id"
        input_fastqs=($(ls ${run_id}*.fastq.gz))
        # 配列の長さによるリードインデックスの定義
        read_indices=("R2" "R1" "I2" "I1")
        if [ ${#input_fastqs[@]} -eq 3 ]; then
            read_indices=("R2" "R1" "I1")
        elif [ ${#input_fastqs[@]} -eq 2 ]; then
            read_indices=("R2" "I1")
        fi
        # リード長の中央値とファイル名の連想配列の作成
        declare -A file_median_lengths
        for file in "${input_fastqs[@]}"; do
            median_length=$(get_median_length $file)
            file_median_lengths["$median_length"]=$file
        done
        # 中央値をソート
        sorted_medians=($(for k in "${!file_median_lengths[@]}"; do echo $k; done | sort -nr))
        # ファイルの改名
        for i in "${!sorted_medians[@]}"; do
            read_index=${read_indices[$i]}
            original_file=${file_median_lengths[${sorted_medians[$i]}]}
            new_file="${sample_id}_S1_L001_${read_index}_001.fastq.gz"
            mv $original_file $new_file
            echo "$original_file renamed to $new_file"
        done
    done
else
    echo "[ERROR] Input should be 'bam' or 'fastqs'"
    exit 1
fi
