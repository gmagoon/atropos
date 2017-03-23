# coding: utf-8
"""Sequence I/O classes: Reading and writing of FASTA and FASTQ files.

TODO
- Sequence.name should be Sequence.description or so (reserve .name for the part
  before the first space)
"""
import sys
from atropos import AtroposError
from atropos.io import STDOUT, xopen
from atropos.io.compression import splitext_compressed
from atropos.util import truncate_string

class FormatError(AtroposError):
    """Raised when an input file (FASTA or FASTQ) is malformatted."""
    pass

class UnknownFileType(AtroposError):
    """Raised when open could not autodetect the file type."""
    pass

## Reading sequences from files ##

class SequenceReader(object):
    """Read possibly compressed files containing sequences.
    
    Args:
        file is a path or a file-like object. In both cases, the file may
            be compressed (.gz, .bz2, .xz).
        mode: The file open mode.
    """
    _close_on_exit = False
    
    def __init__(self, path, mode='r'):
        if isinstance(path, str):
            path = xopen(path, mode)
            self._close_on_exit = True
        self._file = path
    
    @property
    def name(self):
        """The underlying file name.
        """
        return self._file.name
    
    def close(self):
        """Close the underlying file.
        """
        if self._close_on_exit and self._file is not None:
            self._file.close()
            self._file = None
    
    def __enter__(self):
        if self._file is None:
            raise ValueError("I/O operation on closed SequenceReader")
        return self
    
    def __exit__(self, *args):
        self.close()

try:
    from ._seqio import Sequence, FastqReader
except ImportError:
    pass

class ColorspaceSequence(Sequence):
    """Sequence object for colorspace reads.
    """
    def __init__(
            self, name, sequence, qualities, primer=None, name2='',
            original_length=None, match=None, match_info=None, clipped=None,
            insert_overlap=False, merged=False, corrected=0):
        # In colorspace, the first character is the last nucleotide of the
        # primer base and the second character encodes the transition from the
        # primer base to the first real base of the read.
        if primer is None:
            self.primer = sequence[0:1]
            sequence = sequence[1:]
        else:
            self.primer = primer
        if qualities is not None and len(sequence) != len(qualities):
            rname = truncate_string(name)
            raise FormatError(
                "In read named {0!r}: length of colorspace quality "
                "sequence ({1}) and length of read ({2}) do not match (primer "
                "is: {3!r})".format(
                    rname, len(qualities), len(sequence), self.primer))
        super().__init__(
            name, sequence, qualities, name2, original_length, match,
            match_info, clipped, insert_overlap, merged, corrected)
        if not self.primer in ('A', 'C', 'G', 'T'):
            raise FormatError(
                "Primer base is {0!r} in read {1!r}, but it should be one of "
                "A, C, G, T.".format(self.primer, truncate_string(name)))
    
    def __repr__(self):
        fmt_str = \
            '<ColorspaceSequence(name={0!r}, primer={1!r}, sequence={2!r}{3})>'
        qstr = ''
        if self.qualities is not None:
            qstr = ', qualities={0!r}'.format(truncate_string(self.qualities))
        return fmt_str.format(
            truncate_string(self.name), self.primer,
            truncate_string(self.sequence), qstr)
    
    def __getitem__(self, key):
        return self.__class__(
            self.name,
            self.sequence[key],
            self.qualities[key] if self.qualities is not None else None,
            self.primer,
            self.name2,
            self.original_length,
            self.match,
            self.match_info,
            self.clipped,
            self.insert_overlap,
            self.merged,
            self.corrected)

def sra_colorspace_sequence(name, sequence, qualities, name2):
    """Factory for an SRA colorspace sequence (which has one quality value
    too many).
    """
    return ColorspaceSequence(name, sequence, qualities[1:], name2=name2)

class FileWithPrependedLine(object):
    """A file-like object that allows to "prepend" a single line to an already
    opened file. That is, further reads on the file will return the provided
    line and only then the actual content. This is needed to solve the problem
    of autodetecting input from a stream: As soon as the first line has been
    read, we know the file type, but also that line is "gone" and unavailable
    for further processing.
    
    Args:
        file: An already opened file-like object.
        line: A single string (newline will be appended if not included).
    """
    def __init__(self, file, line):
        if not line.endswith('\n'):
            line += '\n'
        self.first_line = line
        self._file = file
    
    def __iter__(self):
        yield self.first_line
        for line in self._file:
            yield line
    
    def close(self):
        """Close the underlying file.
        """
        self._file.close()

class FastaReader(SequenceReader):
    """Reader for FASTA files.
    
    Args:
        file: A path or a file-like object. In both cases, the file may
            be compressed (.gz, .bz2, .xz).
        keep_linebreaks: Whether to keep newline characters in the sequence.
        sequence_class: The class to use when creating new sequence objects.
    """
    def __init__(self, file, keep_linebreaks=False, sequence_class=Sequence):
        super().__init__(file)
        self.sequence_class = sequence_class
        self.delivers_qualities = False
        self._delimiter = '\n' if keep_linebreaks else ''
    
    def __iter__(self):
        """Read next entry from the file (single entry at a time).
        """
        name = None
        seq = []
        for i, line in enumerate(self._file):
            # strip() also removes DOS line breaks
            line = line.strip()
            if not line:
                continue
            if line and line[0] == '>':
                if name is not None:
                    yield self.sequence_class(
                        name, self._delimiter.join(seq), None)
                name = line[1:]
                seq = []
            elif line and line[0] == '#':
                continue
            elif name is not None:
                seq.append(line)
            else:
                raise FormatError(
                    "At line {0}: Expected '>' at beginning of FASTA record, "
                    "but got {1!r}.".format(i+1, truncate_string(line)))
        
        if name is not None:
            yield self.sequence_class(name, self._delimiter.join(seq), None)

class ColorspaceFastaReader(FastaReader):
    """Reads colorspace sequences from a FASTA.
    
    Args:
        path: The file to read.
        keep_linebreaks: Whether to keep linebreaks in wrapped sequences.
    """
    def __init__(self, path, keep_linebreaks=False):
        super().__init__(
            path, keep_linebreaks, sequence_class=ColorspaceSequence)

class ColorspaceFastqReader(FastqReader):
    """Reads colorspace sequences from a FASTQ.
    """
    def __init__(self, path):
        super().__init__(path, sequence_class=ColorspaceSequence)

class SRAColorspaceFastqReader(FastqReader):
    """Reads SRA-formatted colorspace sequences from a FASTQ.
    """
    def __init__(self, file):
        super().__init__(file, sequence_class=sra_colorspace_sequence)

class FastaQualReader(object):
    """Reader for reads that are stored in .(CS)FASTA and .QUAL files.
    
    Args:
        fastafile and qualfile are filenames or file-like objects.
            If a filename is used, then .gz files are recognized.
        sequence_class: The class to use when creating new sequence objects.
    """
    delivers_qualities = True
    
    def __init__(self, fastafile, qualfile, sequence_class=Sequence):
        self.fastareader = FastaReader(fastafile)
        self.qualreader = FastaReader(qualfile, keep_linebreaks=True)
        self.sequence_class = sequence_class
    
    def __iter__(self):
        """Yield Sequence objects.
        """
        # conversion dictionary: maps strings to the appropriate ASCII-encoded
        # character
        conv = dict()
        for i in range(-5, 256 - 33):
            conv[str(i)] = chr(i + 33)
        for fastaread, qualread in zip(self.fastareader, self.qualreader):
            if fastaread.name != qualread.name:
                raise FormatError(
                    "The read names in the FASTA and QUAL file do not match "
                    "({0!r} != {1!r})".format(fastaread.name, qualread.name))
            try:
                qualities = ''.join(
                    [conv[value] for value in qualread.sequence.split()])
            except KeyError as err:
                raise FormatError(
                    "Within read named {0!r}: Found invalid quality "
                    "value {1}".format(fastaread.name, err))
            assert fastaread.name == qualread.name
            yield self.sequence_class(
                fastaread.name, fastaread.sequence, qualities)
    
    def close(self):
        """Close the underlying files.
        """
        self.fastareader.close()
        self.qualreader.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, *args):
        self.close()

class ColorspaceFastaQualReader(FastaQualReader):
    """Reads sequences and qualities from separate files and returns
    :class:`ColorspaceSequence`s.
    
    Args:
        fastafile, qualfile: FASTA files that contain the sequences and
            qualities, respectively.
    """
    def __init__(self, fastafile, qualfile):
        super().__init__(fastafile, qualfile, sequence_class=ColorspaceSequence)

def sequence_names_match(read1, read2):
    """Check whether the sequences read1 and read2 have identical names,
    ignoring a suffix of '1' or '2'. Some old paired-end reads have names that
    end in '/1' and '/2'. Also, the fastq-dump tool (used for converting SRA
    files to FASTQ) appends a .1 and .2 to paired-end reads if option -I is
    used.
    
    Args:
        read1, read2: The sequences to compare.
    
    Returns:
        Whether the sequences are equal.
    """
    name1 = read1.name.split(None, 1)[0]
    name2 = read2.name.split(None, 1)[0]
    if name1[-1:] in '12' and name2[-1:] in '12':
        name1 = name1[:-1]
        name2 = name2[:-1]
    return name1 == name2

class PairedSequenceReader(object):
    """Read paired-end reads from two files. Wraps two SequenceReader instances,
    making sure that reads are properly paired.
    
    Args:
        file1, file2: The pair of files.
        colorspace: Whether the sequences are in colorspace.
        fileformat: A FileFormat instance.
    """
    def __init__(self, file1, file2, colorspace=False, fileformat=None):
        self.reader1 = open_reader(
            file1, colorspace=colorspace, fileformat=fileformat)
        self.reader2 = open_reader(
            file2, colorspace=colorspace, fileformat=fileformat)
        self.delivers_qualities = self.reader1.delivers_qualities
    
    def __iter__(self):
        """Iterate over the paired reads. Each item is a pair of Sequence
        objects.
        """
        # Avoid usage of zip() below since it will consume one item too many.
        it1, it2 = iter(self.reader1), iter(self.reader2)
        while True:
            try:
                read1 = next(it1)
            except StopIteration:
                # End of file 1. Make sure that file 2 is also at end.
                try:
                    next(it2)
                    raise FormatError(
                        "Reads are improperly paired. There are more reads in "
                        "file 2 than in file 1.")
                except StopIteration:
                    pass
                break
            try:
                read2 = next(it2)
            except StopIteration:
                raise FormatError(
                    "Reads are improperly paired. There are more reads in "
                    "file 1 than in file 2.")
            if not sequence_names_match(read1, read2):
                raise FormatError(
                    "Reads are improperly paired. Read name '{0}' in file 1 "
                    "does not match '{1}' in file 2.".format(
                        read1.name, read2.name))
            yield (read1, read2)
    
    def close(self):
        """Close the underlying files.
        """
        self.reader1.close()
        self.reader2.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, *args):
        self.close()

class InterleavedSequenceReader(object):
    """Read paired-end reads from an interleaved FASTQ file.
    
    Args:
        path: The interleaved FASTQ file.
        colorspace: Whether the sequences are in colorspace.
        fileformat: A FileFormat instance.
    """
    def __init__(self, path, colorspace=False, fileformat=None):
        self.reader = open_reader(
            path, colorspace=colorspace, fileformat=fileformat)
        self.delivers_qualities = self.reader.delivers_qualities
    
    def __iter__(self):
        # Avoid usage of zip() below since it will consume one item too many.
        itr = iter(self.reader)
        for read1 in itr:
            try:
                read2 = next(itr)
            except StopIteration:
                raise FormatError(
                    "Interleaved input file incomplete: Last record has no "
                    "partner.")
            if not sequence_names_match(read1, read2):
                raise FormatError(
                    "Reads are improperly paired. Name {0!r} (first) does not "
                    "match {1!r} (second).".format(read1.name, read2.name))
            yield (read1, read2)
    
    def close(self):
        """Close the underlying reader.
        """
        self.reader.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

# TODO: SAM/BAM classes need unit tests

class SAMReader(object):
    """Reader for SAM/BAM files. Paired-end files must be name-sorted. Does
    not support secondary/supplementary reads. This is an abstract class.
    
    Args:
        path: A filename or a file-like object. If a filename, then .gz files
            are supported.
        sequence_class: The class to use when creating new sequence objects.
    """
    def __init__(self, path, sequence_class=Sequence):
        self._close_on_exit = False
        if isinstance(path, str):
            path = xopen(path, 'rb')
            self._close_on_exit = True
        self._file = path
        self.sequence_class = sequence_class
        self.delivers_qualities = True

    def __iter__(self):
        import pysam
        return self._iter(pysam.AlignmentFile(self._file))
    
    def _iter(self, sam):
        """Create an iterator over records in the SAM/BAM file.
        """
        raise NotImplementedError()
    
    def __enter__(self):
        return self
    
    def __exit__(self, *args):
        self.close()
    
    def close(self):
        """Close the underling AlignmentFile.
        """
        if self._close_on_exit and self._file is not None:
            self._file.close()
            self._file = None
        
    def _as_sequence(self, read):
        return self.sequence_class(
            read.query_name,
            read.query_sequence,
            ''.join(chr(33 + q) for q in read.query_qualities))

class SingleEndSAMReader(SAMReader):
    """Reader for single-end SAM/BAM files.
    """
    def _iter(self, sam):
        for read in sam:
            yield self._as_sequence(read)

class Read1SingleEndSAMReader(SAMReader):
    """Reads a paired-end SAM/BAM file as if it were single-end, yielding
    only the first read from each pair.
    """
    def _iter(self, sam):
        for read in sam:
            if read.is_read1:
                yield self._as_sequence(read)

class Read2SingleEndSAMReader(SAMReader):
    """Reads a paired-end SAM/BAM file as if it were single-end, yielding
    only the second read from each pair.
    """
    def _iter(self, sam):
        for read in sam:
            if read.is_read2:
                yield self._as_sequence(read)

class PairedEndSAMReader(SAMReader):
    """Reads pairs of reads from a SAM/BAM file. The file must be name-sorted.
    """
    def _iter(self, sam):
        for reads in zip(sam, sam):
            if reads[0].query_name != reads[1].query_name:
                raise AtroposError(
                    "Consecutive reads {}, {} in paired-end SAM/BAM file do "
                    "not have the same name; make sure your file is "
                    "name-sorted and does not contain any "
                    "secondary/supplementary alignments.",
                    reads[0].query_name, reads[1].query_name)
            
            if reads[0].is_read1:
                assert reads[1].is_read2
            else:
                assert reads[1].is_read1
                reads = (reads[1], reads[0])
            
            yield tuple(self._as_sequence(r) for r in reads)

def paired_to_read1(reader):
    """Generator that yields the first read from an iterator over read pairs.
    """
    for read1, _ in reader:
        yield read1

def paired_to_read2(reader):
    """Generator that yields the second read from an iterator over read pairs.
    """
    for _, read2 in reader:
        yield read2

def open_reader(
        file1, file2=None, qualfile=None, colorspace=False, fileformat=None,
        interleaved=False, single_input_read=None):
    """Open sequence files in FASTA or FASTQ format for reading. This is
    a factory that returns an instance of one of the ...Reader
    classes also defined in this module.
    
    Args:
        file1, file2, qualfile: Paths to regular or compressed files or
        file-like objects. Use file1 if data is single-end. If file2 is also
        provided, sequences are paired. If qualfile is given, then file1 must be
        a FASTA file and sequences are single-end. One of file2 and qualfile
        must always be None (no paired-end data is supported when reading
        qualfiles).
        
        interleaved:If True, then file1 contains interleaved paired-end data.
            file2 and qualfile must be None in this case.
        
        colorspace: If True, instances of the Colorspace... classes
            are returned.
        
        fileformat: If set to None, file format is autodetected from the file
            name extension. Set to 'fasta', 'fastq', 'sra-fastq', 'sam', or
            'bam' to not auto-detect. Colorspace is not auto-detected and must
            always be requested explicitly.
        
        single_input_read: When file1 is a paired-end interleaved or SAM/BAM
            file, this specifies whether to only use the first or second read
            (1 or 2) or to use both reads (None).
    """
    if interleaved and (file2 is not None or qualfile is not None):
        raise ValueError(
            "When interleaved is set, file2 and qualfile must be None")
    if file2 is not None and qualfile is not None:
        raise ValueError("Setting both file2 and qualfile is not supported")
    
    if file2 is not None:
        return PairedSequenceReader(file1, file2, colorspace, fileformat)
    
    if qualfile is not None:
        if colorspace:
            # read from .(CS)FASTA/.QUAL
            return ColorspaceFastaQualReader(file1, qualfile)
        else:
            return FastaQualReader(file1, qualfile)
    
    if fileformat is None and file1 != STDOUT:
        fileformat = guess_format_from_name(file1)
    
    if fileformat is None:
        if file1 == STDOUT:
            file1 = sys.stdin
        for line in file1:
            if line.startswith('#'):
                # Skip comment lines (needed for csfasta)
                continue
            if line.startswith('>'):
                fileformat = 'fasta'
            elif line.startswith('@'):
                fileformat = 'fastq'
            # TODO: guess SAM/BAM from data
            file1 = FileWithPrependedLine(file1, line)
            break
    
    if fileformat is not None:
        fileformat = fileformat.lower()
        if fileformat in ("sam", "bam"):
            if colorspace:
                raise ValueError(
                    "SAM/BAM format is not currently supported for colorspace "
                    "reads")
            if interleaved:
                return PairedEndSAMReader(file1)
            elif single_input_read == 1:
                return Read1SingleEndSAMReader(file1)
            elif single_input_read == 2:
                return Read2SingleEndSAMReader(file1)
            else:
                return SingleEndSAMReader(file1)
        elif interleaved:
            reader = InterleavedSequenceReader(file1, colorspace, fileformat)
            if single_input_read == 1:
                return paired_to_read1(reader)
            elif single_input_read == 2:
                return paired_to_read2(reader)
            else:
                return reader
        elif fileformat == 'fasta':
            fasta_handler = ColorspaceFastaReader if colorspace else FastaReader
            return fasta_handler(file1)
        elif fileformat == 'fastq':
            fastq_handler = ColorspaceFastqReader if colorspace else FastqReader
            return fastq_handler(file1)
        elif fileformat == 'sra-fastq' and colorspace:
            return SRAColorspaceFastqReader(file1)
    
    raise UnknownFileType(
        "File format {0!r} is unknown (expected 'sra-fastq' (only for "
        "colorspace), 'fasta', 'fastq', 'sam', or 'bam').".format(fileformat))

def guess_format_from_name(path, raise_on_failure=False):
    """Detect file format based on the file name.
    
    Args:
        path: The filename to guess.
        raise_on_failure: Whether to raise an exception if the filename cannot
            be detected.
    
    Returns:
        The format name.
    """
    name = None
    if isinstance(path, str):
        name = path
    elif hasattr(path, "name"):	 # seems to be an open file-like object
        name = path.name
    
    if name:
        name, ext1, _ = splitext_compressed(name)
        ext = ext1.lower()
        if ext in ['.fasta', '.fa', '.fna', '.csfasta', '.csfa']:
            return 'fasta'
        elif ext in ['.fastq', '.fq'] or (
                ext == '.txt' and name.endswith('_sequence')):
            return 'fastq'
        elif ext in ('.sam', '.bam'):
            return ext[1:]
    
    if raise_on_failure:
        raise UnknownFileType(
            "Could not determine whether file {0!r} is FASTA or FASTQ: file "
            "name extension {1!r} not recognized".format(path, ext))

## Converting reads to strings ##

class SequenceFileFormat(object):
    """Base class for sequence formatters.
    """
    def format(self, read):
        """Format a Sequence as a string.
        
        Args:
            read: The Sequence object.
        
        Returns:
            A string representation of the sequence object in the sequence
            file format.
        """
        raise NotImplementedError()

class FastaFormat(SequenceFileFormat):
    """FASTA SequenceFileFormat.
    
    Args:
        line_length: Max line length (in characters), or None. Determines
            whether and how lines are wrapped.
    """
    def __init__(self, line_length=None):
        self.text_wrapper = None
        if line_length:
            from textwrap import TextWrapper
            self.text_wrapper = TextWrapper(width=line_length)
    
    def format(self, read):
        return self.format_entry(read.name, read.sequence)
    
    def format_entry(self, name, sequence):
        """Convert a sequence record to a string.
        """
        if self.text_wrapper:
            sequence = self.text_wrapper.fill(sequence)
        return "".join((">", name, "\n", sequence, "\n"))

class ColorspaceFastaFormat(FastaFormat):
    """FastaFormat in which sequences are in colorspace.
    """
    def format(self, read):
        return self.format_entry(read.name, read.primer + read.sequence)

class FastqFormat(SequenceFileFormat):
    """FASTQ SequenceFileFormat.
    """
    def format(self, read):
        return self.format_entry(
            read.name, read.sequence, read.qualities, read.name2)
    
    def format_entry(self, name, sequence, qualities, name2=""):
        """Convert a sequence record to a string.
        """
        return "".join((
            '@', name, '\n',
            sequence, '\n+',
            name2, '\n',
            qualities, '\n'))

class ColorspaceFastqFormat(FastqFormat):
    """FastqFormat in which sequences are in colorspace.
    """
    def format(self, read):
        return self.format_entry(
            read.name, read.primer + read.sequence, read.qualities)

class SingleEndFormatter(object):
    """Wrapper for a SequenceFileFormat for single-end data.
    
    Args:
        seq_format: The SequenceFileFormat object.
        file1: The single-end file.
    """
    def __init__(self, seq_format, file1):
        self.seq_format = seq_format
        self.file1 = file1
        self.written = 0
        self.read1_bp = 0
        self.read2_bp = 0
    
    def format(self, result, read1, read2=None):
        """Format read(s) and add them to `result`.
        
        Args:
            result: A dict mapping file names to lists of formatted reads.
            read1, read2: The reads to format.
        """
        result[self.file1].append(self.seq_format.format(read1))
        self.written += 1
        self.read1_bp += len(read1)
    
    @property
    def written_bp(self):
        """Tuple of base-pairs written (read1_bp, read2_bp).
        """
        return (self.read1_bp, self.read2_bp)

class InterleavedFormatter(SingleEndFormatter):
    """Format read pairs as successive reads in an interleaved file.
    """
    def format(self, result, read1, read2=None):
        result[self.file1].extend((
            self.seq_format.format(read1),
            self.seq_format.format(read2)))
        self.written += 1
        self.read1_bp += len(read1)
        self.read2_bp += len(read2)

class PairedEndFormatter(SingleEndFormatter):
    """Wrapper for a SequenceFileFormat. Both reads in a pair are formatted
    using the specified format.
    """
    def __init__(self, seq_format, file1, file2):
        super(PairedEndFormatter, self).__init__(seq_format, file1)
        self.file2 = file2
    
    def format(self, result, read1, read2):
        result[self.file1].append(self.seq_format.format(read1))
        result[self.file2].append(self.seq_format.format(read2))
        self.written += 1
        self.read1_bp += len(read1)
        self.read2_bp += len(read2)

def create_seq_formatter(file1, file2=None, interleaved=False, **kwargs):
    """Create a formatter, deriving the format name from the file extension.
    
    Args:
        file1, file2: Output files.
        interleaved: Whether the output should be interleaved (file2 must be
            None).
        kwargs: Additional arguments to pass to :method:`get_format`.
    """
    seq_format = get_format(file1, **kwargs)
    if file2 is not None:
        return PairedEndFormatter(seq_format, file1, file2)
    elif interleaved:
        return InterleavedFormatter(seq_format, file1)
    else:
        return SingleEndFormatter(seq_format, file1)

def get_format(
        path, fileformat=None, colorspace=False, qualities=None,
        line_length=None):
    """Create a FileFormat instance.
    
    Args:
        path: The filename.
        
        fileformat: If set to None, file format is autodetected from the file
        name extension. Set to 'fasta', 'fastq', or 'sra-fastq' to not
        auto-detect. Colorspace is not auto-detected and must always be
        requested explicitly.
        
        colorspace: If True, instances of the Colorspace... formats are
            returned.
        
        qualities: When fileformat is None, this can be set to True or False to
            specify whether the written sequences will have quality values.
            This is is used in two ways:
            * If the output format cannot be determined (unrecognized extension
              etc), no exception is raised, but fasta or fastq format is chosen
              appropriately.
            * When False (no qualities available), an exception is raised when
              the auto-detected output format is FASTQ.
    
    Returns:
        A FileFormat object.
    """
    if fileformat is None:
        fileformat = guess_format_from_name(
            path, raise_on_failure=qualities is None)
    
    if fileformat is None:
        if qualities is True:
            # Format not recognized, but know we want to write reads with
            # qualities.
            fileformat = 'fastq'
        elif qualities is False:
            # Same, but we know that we want to write reads without qualities.
            fileformat = 'fasta'
    
    if fileformat is None:
        raise UnknownFileType("Could not determine file type.")
    
    if fileformat == 'fastq' and qualities is False:
        raise ValueError(
            "Output format cannot be FASTQ since no quality values are "
            "available.")
    
    fileformat = fileformat.lower()
    if fileformat == 'fasta':
        if colorspace:
            return ColorspaceFastaFormat(line_length)
        else:
            return FastaFormat(line_length)
    elif fileformat == 'fastq':
        if colorspace:
            return ColorspaceFastqFormat()
        else:
            return FastqFormat()
    else:
        raise UnknownFileType(
            "File format {0!r} is unknown (expected 'fasta' or "
            "'fastq').".format(fileformat))
