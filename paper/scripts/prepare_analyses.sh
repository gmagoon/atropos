#!/bin/bash

# This script will generate the commands to run the analyses for the
# Atropos paper.
#
# For each error profile, we run Atropos, SeqPurge, and Skewer using
# equivalent (or as similar as possible) arguments. The tests are run
# both locally (Late 2013 Mac Pro, 3.7 GHz quad-core Xeon E5, 32 GB
# memory) and on a cluster (SL6, ???, connected to Isilon NAS over
# InfiniBand??). Atropos is run both with and without a separate Writer
# process. The tests are run on both simulated data and real data.
#
# Call: prepare_analyses.sh \
# -t <threads> -r <root dir> -o <output dir> -g <genome> -a <annotations>

# A POSIX variable; reset in case getopts has been used
# previously in the shell.
OPTIND=1

# Set default values
threads=8
script_dir=`pwd`
root=`dirname $script_dir`
outdir_root='results'
mode='local'
# reference genome (for mapping real reads)
genome_dir=$root/data/reference
genome_fasta=$genome_dir/ref.fasta
# transcriptome annotations
annotations=$root/data/reference/gencode.v19.gff

while getopts "t:r:o:g:a:m:" opt; do
    case "$opt" in
    t)
        threads=$OPTARG
        ;;
    r)
        root=$OPTARG
        ;;
    o)
        outdir_root=$OPTARG
        ;;
    g)
        genome_dir=$OPTARG
        ;;
    a)
        annotations=$OPTARG
        ;;
    m)
        mode=$OPTARG
        ;;
    esac
done

shift $((OPTIND-1))

[ "$1" = "--" ] && shift

run="run_t${threads}_${mode}"
commands="commands_t${threads}"
align_commands="align_commands_t${threads}"
sort_commands="sort_commands_t${threads}"
bedops_commands="bedops_commands_t${threads}"
summarize_commands="summarize_commands_t${threads}"

for f in $run $commands $align_commands $sort_commands $bedops_commands $summarize_commands
do
    rm -f $f
    echo "#!/bin/bash" >> $f
done

echo "# Generated by prepare_analyses.sh with arguments" \
"threads: $threads, command file: $commands, root: $root," \
"results: $outdir_root, genome_dir: $genome_dir, annotations: $annotations," \
"mode: $mode, unused args: $@" >> $run

cat >> $run <<-EOM1
GB_PER_PROCESS=4
ALIGN_GB_PER_PROCESS=64
SORT_GB_PER_PROCESS=8
OVERLAP_GB_PER_PROCESS=16
export DYLD_LIBRARY_PATH=$DYLD_LIBRARY_PATH:$ATROPOS_ROOT/software/bin
EOM1

for d in simulated wgbs rna
do
    echo "mkdir -p $outdir_root/$d" >> $run
done

## Constants

# binaries
ATROPOS=atropos
SEQPURGE=$root/software/bin/SeqPurge
SKEWER=$root/software/bin/skewer
BWA=bwa
STAR=STAR
BWAMETH=bwameth.py
SAMTOOLS=samtools
# These are in the bedops package
BAM2BED=bam2bed
BEDMAP=bedmap
# minimum read length after trimming
MIN_LEN=25
# number of reads to process in a batch
# (also used as prefetch size for SeqPurge)
BATCH_SIZE=5000

for err in 001 005 01 real_rna real_wgbs
do
  # In the simulated data, we don't do error correction in Atropos
  # or SeqPurge because it shouldn't affect the outcome of adapter
  # trimming and increases the processing time of the benchmarking
  # scripts (error correction can't be turned off in Skewer). Also,
  # the simulated data has a lower max error rate than the real data.
  
  if [ "$err" == "real_rna" ]
  then
    outdir=$outdir_root/rna
    base=$root/data/rna/rna
    fq1=$root/data/rna/rna.1.fq.gz
    fq2=$root/data/rna/rna.2.fq.gz
    # download data
    if [ ! -f $fq1 ]
    then
      mkdir -p $root/data/rna
      fastq-dump --split-files -A SRR521458
      mv SRR521459_1.fastq $fq1
      mv SRR521459_2.fastq $fq2
    fi
    quals='0'
    aligners='insert'
    atropos_extra='--insert-match-error-rate 0.3 -e 0.2 --correct-mismatches liberal -w 15,30,25'
    seqpurge_extra='-ec -match_perc 70'
    skewer_extra='-r 0.3'
    ADAPTER1="AGATCGGAAGAGCGGTTCAGCAGGAATGCCGAGACCGATATCGTATGCCGTCTTCTGCTTG" # Custom?
    ADAPTER2="AGATCGGAAGAGCGTCGTGTAGGGAAAGAGTGTAGATCTCGGTGGTCGCCGTATCATT" # TruSeq Universal
  elif [ "$err" == "real_wgbs" ]
  then
      outdir=$outdir_root/wgbs
      fq1=$root/data/wgbs/wgbs.1.fq.gz
      fq2=$root/data/wgbs/wgbs.2.fq.gz
      # download data
      if [ ! -f $fq1 ]
      then
        mkdir -p $root/data/wgbs
        wget -qO- https://www.encodeproject.org/files/ENCFF798RSS/@@download/ENCFF798RSS.fastq.gz | gunzip | head -4000000 | gzip > $fq1
        wget -qO- https://www.encodeproject.org/files/ENCFF113KRQ/@@download/ENCFF113KRQ.fastq.gz | gunzip | head -4000000 | gzip > $fq2
      fi
      quals='0 20'
      aligners='insert'
      atropos_extra='--insert-match-error-rate 0.3 -e 0.2 --correct-mismatches liberal'
      seqpurge_extra='-ec -match_perc 70'
      skewer_extra='-r 0.3'
      ADAPTER1="AGATCGGAAGAGCACACGTCTGAACTCCAGTCACCAGATCATCTCGTATGCCGTCTTCTGCTTG" # TruSeq index 7
      ADAPTER2="AGATCGGAAGAGCGTCGTGTAGGGAAAGAGTGTAGATCTCGGTGGTCGCCGTATCATT" # TruSeq universal
  else
      outdir=$outdir_root/simulated
      fq1=$root/data/simulated/sim_${err}.1.fq
      fq2=$root/data/simulated/sim_${err}.2.fq
      quals='0'
      atropos_extra='--insert-match-error-rate 0.20 -e 0.10'
      seqpurge_extra='-match_perc 80'
      skewer_extra='-r 0.20'
      aligners='adapter insert'
      ADAPTER1="AGATCGGAAGAGCACACGTCTGAACTCCAGTCACACAGTGATCTCGTATGCCGTCTTCTGCTTG"
      ADAPTER2="AGATCGGAAGAGCGTCGTGTAGGGAAAGAGTGTAGATCTCGGTGGTCGCCGTATCATT"
  fi

  # Generate commands for trimming
  for qcut in $quals
  do
    for aligner in $aligners
    do
        profile="atropos_${threads}_${err}_q${qcut}_${aligner}_writercomp"
        echo ">&2 echo $profile && /usr/bin/time -p" \
        "$ATROPOS -T $threads --aligner $aligner --op-order GACQW" \
        "-a $ADAPTER1 -A $ADAPTER2 -q $qcut --trim-n" \
        "-m $MIN_LEN --batch-size $BATCH_SIZE" \
        "--report-file ${outdir}/${profile}.report.txt" \
        "--no-default-adapters --no-cache-adapters" \
        "-o ${outdir}/${profile}.1.fq.gz" \
        "-p ${outdir}/${profile}.2.fq.gz" \
        "--log-level ERROR --quiet $atropos_extra" \
        "--compression writer -pe1 $fq1 -pe2 $fq2" >> $commands
        
        profile="atropos_${threads}_${err}_q${qcut}_${aligner}_workercomp"
        echo ">&2 echo $profile && /usr/bin/time -p" \
        "$ATROPOS -T $threads --aligner $aligner --op-order GACQW" \
        "-a $ADAPTER1 -A $ADAPTER2 -q $qcut --trim-n" \
        "-m $MIN_LEN --batch-size $BATCH_SIZE " \
        "--report-file ${outdir}/${profile}.report.txt" \
        "--no-default-adapters --no-cache-adapters" \
        "-o ${outdir}/${profile}.1.fq.gz" \
        "-p ${outdir}/${profile}.2.fq.gz" \
        "--log-level ERROR --quiet $atropos_extra" \
        "--compression worker -pe1 $fq1 -pe2 $fq2" >> $commands
        
        profile="atropos_${threads}_${err}_q${qcut}_${aligner}_nowriter"
        echo ">&2 echo $profile && /usr/bin/time -p" \
        "$ATROPOS -T $threads --aligner $aligner --op-order GACQW" \
        "-a $ADAPTER1 -A $ADAPTER2 -q $qcut --trim-n" \
        "-m $MIN_LEN --batch-size $BATCH_SIZE " \
        "--report-file ${outdir}/${profile}.report.txt" \
        "--no-default-adapters --no-cache-adapters" \
        "-o ${outdir}/${profile}.1.fq.gz" \
        "-p ${outdir}/${profile}.2.fq.gz" \
        "--log-level ERROR --quiet $atropos_extra" \
        "--no-writer-process -pe1 $fq1 -pe2 $fq2" >> $commands
    done
    
    profile="seqpurge_${threads}_${err}_q${qcut}"
    echo ">&2 echo $profile && /usr/bin/time -p" \
    "$SEQPURGE -in1 $fq1 -in2 $fq2" \
    "-out1 ${outdir}/${profile}.1.fq.gz" \
    "-out2 ${outdir}/${profile}.2.fq.gz" \
    "-a1 $ADAPTER1 -a2 $ADAPTER2" \
    "-qcut $qcut -min_len $MIN_LEN" \
    "-threads $threads -prefetch $BATCH_SIZE" \
    "$seqpurge_extra" \
    "-summary ${outdir}/${profile}.summary" >> $commands

    profile="skewer_${threads}_${err}_q${qcut}"
    echo ">&2 echo $profile && /usr/bin/time -p" \
    "$SKEWER -m pe -l $MIN_LEN $skewer_extra" \
    "-o ${outdir}/${profile} -z --quiet" \
    "-x $ADAPTER1 -y $ADAPTER2 -t $threads" \
    "-q $qcut $n $fq1 $fq2 > ${outdir}/${profile}.summary.txt" >> $commands
  done

  # Generate commands to map reads
  if [ "$err" == "real_rna" ]
  then
      STAR_INDEX_DIR="$genome_dir/STAR"
      
      if [ ! -d $STAR_INDEX_DIR ]
      then
        echo "STAR index does not exist; make sure to build it before running the align commands"
      fi
      
      echo "./star_align.sh unmapped $base $threads $STAR_INDEX_DIR" >> $align_commands
      echo "$SAMTOOLS sort -n -O bam -@ $threads -o ${outdir}/untrimmed.sorted.bam" \
      "${outdir}/untrimmed_rnaAligned.out.bam" >> $sort_commands
      echo "$BAM2BED --all-reads --do-not-sort < ${outdir}/untrimmed.sorted.bam" \
      "| cut -f 1-6 | bedmap --delim '\t' --echo --echo-map-id - $annotations" \
      "> ${outdir}/untrimmed.overlap.txt" >> $bedops_commands

      for profile in \
        atropos_${threads}_real_wgs_q${qcut}_insert_workercomp \
        seqpurge_${threads}_real_wgs_q${qcut} \
        skewer_${threads}_real_wgs_q${qcut}
      do
          echo "./star_align.sh ${profile} ${outdir}/${profile} $threads $STAR_INDEX_DIR" >> $align_commands
          echo "$SAMTOOLS sort -n -O bam -@ $threads -o ${outdir}/${profile}.sorted.bam" \
          "${outdir}/${profile}_rnaAligned.out.bam" >> $sort_commands
          echo "$BAM2BED --all-reads --do-not-sort < ${outdir}/${profile}.sorted.bam" \
          "| cut -f 1-6 | bedmap --delim '\t' --echo --echo-map-id -" \
          "$annotations > ${outdir}/${profile}.overlap.txt" >> $bedops_commands
      done
      
      echo "python summarize_real_trimming_accuracy.py -d ${outdir}" \
      "-o ${outdir}/accuracy.txt -H ${outdir}/trimmed_hists.txt" \
      "--no-edit-distance --no-progress mna -B '{name}.overlap.txt'" >> $summarize_commands
  elif [ "$err" == "real_wgbs" ]
  then
    if [ ! -f $genome_dir/bwa-meth/ref.fasta.bwameth.c2t ]
    then
      echo "bwa-meth index does not exist; make sure to build it before running the align commands"
    fi
    
    # map the untrimmed reads
    rg="@RG\tID:untrimmed\tSM:untrimmed\tLB:untrimmed\tPL:ILLUMINA"
    echo "$BWAMETH -z -t ${threads} -o ${outdir}/untrimmed_wgbs.bam" \
    "--read-group '$rg' --reference $genome_dir/bwa-meth/ref $fq1 $fq2" >> $align_commands
    echo "$SAMTOOLS sort -n -O bam -@ $threads -o" \
    "$outdir/untrimmed_wgbs.sorted.bam $outdir/untrimmed_wgbs.bam" >> $sort_commands
  
    # map the trimmed reads
    for qcut in 0 20
    do
      for profile in \
        atropos_${threads}_real_wgbs_q${qcut}_insert_workercomp \
        seqpurge_${threads}_real_wgbs_q${qcut} \
        skewer_${threads}_real_wgbs_q${qcut}
      do
          rg="@RG\tID:${profile}\tSM:${profile}\tLB:${profile}\tPL:ILLUMINA"
          fq1=$outdir/${profile}.1.fq.gz
          fq2=$outdir/${profile}.2.fq.gz
          echo "$BWAMETH -z -t ${threads} -o ${outdir}/$profile.bam " \
          "--read-group '$rg' --reference $genome_dir/bwa-meth/ref $fq1 $fq2" >> $align_commands
          echo "$SAMTOOLS sort -n -O bam -@ $threads -o " \
          "$outdir/$profile.sorted.bam $outdir/$profile.bam" >> $sort_commands
      done
    done
    
    echo "python summarize_real_trimming_accuracy.py -d ${outdir}" \
    "-o ${outdir}/accuracy.txt -H ${outdir}/trimmed_hists.txt" \
    "--no-edit-distance --no-progress" >> $summarize_commands
  else
      mkdir -p $outdir/simulated_accuracy
      for profile in \
        atropos_4_${err}_q0_adapter_writercomp \
        atropos_4_${err}_q0_insert_writercomp \
        seqpurge_4_${err}_q0 \
        skewer_4_${err}_q0-trimmed-pair
      do
        echo "python summarize_simulated_trimming_accuracy.py" \
        "-a1 $root/data/simulated/sim_${err}.1.aln" \
        "-a2 $root/data/simulated/sim_${err}.2.aln" \
        "-r1 $outdir/$profile.1.fq.gz -r2 $outdir/$profile.2.fq.gz" \
        "-o $outdir/simulated_accuracy/$profile.txt" \
        "-s $outdir/simulated_accuracy/$profile.summary.txt" \
        "-t $outdir/simulated_accuracy/table.txt" \
        "--name $profile" >> $summarize_commands
    done
  fi
done

chmod +x $commands
chmod +x $align_commands
chmod +x $sort_commands
chmod +x $bedops_commands
chmod +x $summarize_commands

if [ "$mode" == "local" ]
then

cat >> $run <<-EOM2
# summarize timing
timing_commands="timing_commands_t${threads}"
rm -f $timing_commands
echo "python summarize_timing_info.py -i $outdir/timing_local_t4.txt --output-format latex" \
  "-o $root/results/timing_local_table.latex --table-name 'local-timing'" \
  "--table-caption 'Execution time for programs running on desktop with 4 threads.'" >> $timing_commands

rm -f timing_log_${threads}.txt
./commands_t${threads}_shuf 2>> ../results/timing_log_${threads}.txt && \
./rename_outputs && \
./align_commands_t${threads} && \
./sort_commands_t${threads} && \
./bedops_commands_t${threads} && \
./summarize && \
./$timing_commands
EOM2

elif [ "$mode" == "cluster" ]
then

cat >> $run <<-EOM3
timing_commands="timing_commands_t${threads}"
rm -f $timing_commands
trimJID=`swarm --jobid --threads-per-process ${threads} --gb-per-process $GB_PER_PROCESS --file commands_t${threads}`
# rename skewer outputs
renameJID=`qsub -hold_jid $trimJID rename_outputs`
# map reads
alignJID=`swarm --jobid --hold_jid $renameJID --threads-per-process ${threads} --gb-per-process $ALIGN_GB_PER_PROCESS --file align_commands_t${threads}`
# summarize timing
qsub -b y -hold_jid $alignJID cat commands_t*.e* | python summarize_timing_info.py --output-format latex -o $root/results/timing_cluster_table.latex --table-name 'cluster-timing' --table-caption 'Execution time for programs running on a cluster.'
# name-sort reads
sortJID=`swarm --jobid --hold_jid $alignJID --threads-per-process ${threads} --gb-per-process $SORT_GB_PER_PROCESS --file sort_commands_t${threads}`
# overlap RNA-seq alignments with GENCODE annotations
overlapJID=`swarm --jobid --hold_jid $sortJID --gb-per-process $OVERLAP_GB_PER_PROCESS --file bedops_commands_t${threads}`
# summarize trimming accuracy
swarm --hold_jid $overlapJID --file summarize_commands
EOM3

fi
