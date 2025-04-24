#!/bin/bash -f
#PBS -S /bin/bash
#PBS -l nodes=1:ppn=@nthread@:@cluster@
#PBS -q @cluster@
#PBS -N @jobname@
#PBS -j eo
#PBS -m ae
#PBS -e @log@
