#!/bin/bash
#PBS -S /bin/bash
#PBS -l nodes=1:ppn=%nthread/:%cluster_server/
#PBS -q %cluster_server/
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
commands=("STAR")
for command in "${commands[@]}"; do
  if command -v "$command" >/dev/null 2>&1; then
    echo "[CHECK] $command: Resolved."
  else
    echo "[CHECK] $command: Could not resolve."
    exit 1
  fi
done
##################

## Auto-detect 10x chemistry version ##
detect_chemistry() {
  local fq_path="$1"

  # Find first R1 file
  local r1_file=$(find "$fq_path" \( -name "*_R1_*.fastq.gz" -o -name "*_R1_*.fq.gz" \) | head -1)

  if [ -z "$r1_file" ]; then
    echo "ERROR: Could not find R1 file in $fq_path" >&2
    exit 1
  fi

  # Check barcode length from first 1000 reads (use mode length)
  local bc_length=$(zcat "$r1_file" | head -4000 | awk 'NR%4==2 {print length($0)}' | sort | uniq -c | sort -rn | head -1 | awk '{print $2}')

  # Validate bc_length
  if [ -z "$bc_length" ] || ! [[ "$bc_length" =~ ^[0-9]+$ ]]; then
    echo "ERROR: Could not determine barcode length from $r1_file" >&2
    exit 1
  fi

  # 10x chemistry by R1 length:
  # v2: 16bp CB + 10bp UMI = 26bp
  # v3: 16bp CB + 12bp UMI = 28bp
  if [ "$bc_length" -eq 28 ]; then
    echo "v3"
  elif [ "$bc_length" -eq 26 ]; then
    echo "v2"
  else
    # Fallback: if close to 28, assume v3; otherwise v2
    if [ "$bc_length" -ge 27 ]; then
      echo "v3"
    else
      echo "v2"
    fi
  fi
}

## Set chemistry-specific parameters ##
CHEMISTRY="%chemistry/"
if [ "$CHEMISTRY" = "auto" ]; then
  CHEMISTRY=$(detect_chemistry "%fq_path/")
  echo "[INFO] Auto-detected 10x chemistry: $CHEMISTRY"
fi

# Set parameters based on chemistry
if [ "$CHEMISTRY" = "v3" ]; then
  CB_LEN=16
  UMI_LEN=12
  WHITELIST="${CELLINE_10X_WHITELISTS:-$HOME/.celline/whitelists}/737K-august-2016.txt"
elif [ "$CHEMISTRY" = "v2" ]; then
  CB_LEN=16
  UMI_LEN=10
  WHITELIST="${CELLINE_10X_WHITELISTS:-$HOME/.celline/whitelists}/737K-august-2016.txt"
else
  echo "ERROR: Unknown chemistry: $CHEMISTRY" >&2
  exit 1
fi

# Check whitelist exists
if [ ! -f "$WHITELIST" ]; then
  echo "ERROR: Whitelist not found: $WHITELIST" >&2
  echo "Please set CELLINE_10X_WHITELISTS environment variable or download whitelists" >&2
  exit 1
fi

## Prepare FASTQ files ##
cd "%dist_dir/"
rm -rf "./counted"
mkdir -p "./counted"

# Find R1 and R2 files
R1_FILES=$(find "%fq_path/" \( -name "*_R1_*.fastq.gz" -o -name "*_R1_*.fq.gz" \) | sort | tr '\n' ',' | sed 's/,$//')
R2_FILES=$(find "%fq_path/" \( -name "*_R2_*.fastq.gz" -o -name "*_R2_*.fq.gz" \) | sort | tr '\n' ',' | sed 's/,$//')

if [ -z "$R1_FILES" ] || [ -z "$R2_FILES" ]; then
  echo "ERROR: Could not find R1 and R2 FASTQ files in %fq_path/" >&2
  exit 1
fi

echo "[INFO] R1 files: $R1_FILES"
echo "[INFO] R2 files: $R2_FILES"
echo "[INFO] Using whitelist: $WHITELIST"
echo "[INFO] CB length: $CB_LEN, UMI length: $UMI_LEN"

## Run STARsolo ##
STAR \
  --runThreadN %nthread/ \
  --genomeDir %genome_dir/ \
  --readFilesIn $R2_FILES $R1_FILES \
  --readFilesCommand zcat \
  --outFileNamePrefix ./counted/ \
  --soloType CB_UMI_Simple \
  --soloCBwhitelist $WHITELIST \
  --soloCBlen $CB_LEN \
  --soloUMIlen $UMI_LEN \
  --soloFeatures %feature_type/ \
  --soloCBmatchWLtype 1MM_multi_Nbase_pseudocounts \
  --soloUMIdedup 1MM_All \
  --soloUMIfiltering MultiGeneUMI \
  --soloCellFilter EmptyDrops_CR \
  --outSAMtype BAM SortedByCoordinate \
  --outSAMattributes CB UB GX GN \
  --limitBAMsortRAM 32000000000

# Check if STARsolo succeeded
if [ $? -ne 0 ]; then
  echo "ERROR: STARsolo failed" >&2
  exit 1
fi

## Create Cell Ranger-compatible structure ##
# STARsolo outputs to Solo.out/{feature_type}/
# We create symlink: counted/outs -> Solo.out/{feature_type}/filtered

FEATURE_TYPE="%feature_type/"
STARSOLO_OUT="./counted/Solo.out/$FEATURE_TYPE"

if [ ! -d "$STARSOLO_OUT/filtered" ]; then
  echo "ERROR: STARsolo output not found: $STARSOLO_OUT/filtered" >&2
  exit 1
fi

# Create outs symlink for compatibility with Celline pipeline
# Note: Symlink target is relative to link location (./counted/)
cd "./counted"
ln -sf "Solo.out/$FEATURE_TYPE/filtered" "outs"
cd ..

echo "[SUCCESS] STARsolo completed successfully"
echo "[INFO] Output directory: ./counted/outs -> Solo.out/$FEATURE_TYPE/filtered"
