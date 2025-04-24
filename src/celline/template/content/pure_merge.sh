#!/bin/bash
#PBS -S /bin/bash
#PBS -l nodes=1:ppn=%nthread/:%cluster_server/
#PBS -q %cluster_server/
#PBS -N %jobname/
#PBS -j eo
#PBS -m ae
#PBS -e %logpath/

if [ -e "$HOME/.bashrc" ]; then
    source "$HOME/.bashrc"
fi
if [ -e "$HOME/.zshrc" ]; then
    zsh "$HOME/.zshrc"
fi
%r_path/\
    "%exec_root//celline/template/hook/R/pure_merge.R"\
    "%sample_ids/"\
    "%project_ids/"\
    "%all_bcmat_path/"\
    "%all_data_sample_dir_path/"\
    "%outfile_path/"\
    "%logpath_runtime/"\
    "%project_name/"