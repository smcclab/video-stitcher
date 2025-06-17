"""Functions for processing videos using FFMPEG.
The core functionality is gathering data from videos, re-encoding 
with known settings and overlaid titles, and collating multiple videos together.
This file doesn't know about students, groups, or time, just about files and videos.
"""
import os
import subprocess
import json
import click


def probe(filename):
    """Runs ffprobe on a given file.
    """
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            filename,
        ],
        capture_output=True,
    )
    return json.loads(proc.stdout.decode("utf-8"))


def loudness_probe(filename):
    """get the loudness levels - necessary for proper 2-pass normalisation

    this seems (according to the internet) to require ffmpeg, not ffprobe, so
    it can't be combined with the 'ffprobe()' function above.

    magic values from
    http://peterforgacs.github.io/2018/05/20/Audio-normalization-with-ffmpeg/

    """
    proc = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-i",
            filename,
            "-af",
            "loudnorm=I=-23:LRA=7:tp=-2:print_format=json",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
    )
    # click.secho(f"Loudness Probe Result: {proc}", fg='blue')

    ## this output goes to stderr for some reason
    output = proc.stderr.decode("utf-8")

    ## The string trimming below extracts the structured output from ffmpeg.
    ## If this fails, need to print out the ffmpeg output and figure out
    ## the string trimming again.

    # click.secho(output, fg="blue")
    ## find up to the 'beginning of output' marker
    output = output[output.find("[Parsed_loudnorm_0") :]
    ## strip the 'beginning of output' marker line
    output = output[output.find("\n") :]
    ## strip extra text printed after the structured output.
    output = output[: output.find("[out#0")]
    # click.secho(output, fg="yellow")

    try:
        output_dict = json.loads(output)
    except Exception as e:
        click.secho(f"Loudness probe failed! Need to check FFMPEG output trimming: {e}", fg="red")
        click.secho(f"Output needs to look more like JSON:\n{output}", fg="yellow")
        raise e
    return output_dict


def video_dimensions(filename):
    """Returns the dimension of a video as a tuple.
    """
    for stream in probe(filename)["streams"]:
        if stream["codec_type"] == "video":
            return (int(stream["width"]), int(stream["height"]))

    raise ValueError(f"no video streams found in {filename}")


def video_duration(filename):
    """Returns the duration of a video in seconds.
    """
    duration = float(probe(filename)["format"]["duration"])
    # click.secho(f"Duration of {filename} is {duration}.")
    return duration


def run_ffmpeg(args, verbose=False):
    """Runs ffmpeg with given arguments.
    """
    if verbose:
        click.secho("FFMPEG Arguments:", fg="blue")
        click.secho(args, fg="blue")
    proc_outcome = subprocess.run(["ffmpeg"] + args)
    # if proc_outcome["returncode"] == 1:
    #     click.secho(f"FFMPEG failed! Call was: {proc_outcome}", fg='red')
    return proc_outcome

def escape_ffmpeg_text(text):
    # Escape characters that are special in ffmpeg filter context
    return text.replace("\\", "\\\\").replace("'", "\\\\\\'").replace(":", "\\:")


def process_video(input_path, title_text, output_dir, output_ext=".mp4", verbose=False):
    """ Re-encodes a video from the input_path to output_dir with a title overlay and normalised sound.
    """
    output_path = (
        output_dir / f"{input_path.stem}-processed{output_ext}"
    )
    if output_path.exists() and os.path.getmtime(output_path) >= os.path.getmtime(input_path):
        # only process if input newer than output
        if verbose:
            click.secho(f"Skip processing {title_text}: already processed.", fg='blue')
        return output_path
    else: 
        if verbose:
            click.secho(f"processing video: {input_path.as_posix()}", fg='green')

    loudness_params = loudness_probe(input_path)
    loudness_params['input_i'] = str(min(float(loudness_params['input_i']), 0))
    if verbose:
        click.secho(f"Loudness params for {input_path}:", fg='blue')
    if (loudness_params['input_i'] == "-inf"):
        click.secho(f"Processing Error! Silent file {input_path}, true peak={loudness_params['input_tp']}, not normalising", fg="red")
        loudness_params['input_i'] = -99 # convert -inf to -99
        loudness_params['input_tp'] = -99 # convert -inf to -99
        loudness_params['target_offset'] = 0 # will be inf, but silent so don't both changing gain.
    if verbose:
        click.secho(loudness_params, fg="blue")

    width = 1920
    height = 1080
    framerate = 30
    font_size = 60
    escaped_title_text = escape_ffmpeg_text(title_text)
    # escaped_title_text = title_text

    run_ffmpeg(
        [
            "-i",
            input_path,
            # workaround for the "Too many packets buffered for output stream" error
            "-max_muxing_queue_size",
            "99999",
            # normalise loudness according to EBU R128 standard
            "-af",
            "loudnorm=I=-23:LRA=7:tp=-2:measured_I={input_i}:measured_LRA={input_lra}:measured_tp={input_tp}:measured_thresh={input_thresh}:offset={target_offset}".format_map(
                loudness_params
            ),
            # here begins the complex filter command
            "-filter_complex",
            # scale/pad to full HD
            f"fps={framerate},"
            + f"scale=min(iw*{height}/ih\,{width}):min({height}\,ih*{width}/iw),pad={width}:{height}:({width}-iw)/2:({height}-ih)/2:color=white,setsar=sar=1/1,"
            # draw the name box at the bottom
            + f"drawbox=y=ih-{2*font_size}:color=black@0.3:width=iw:height={2*font_size}:t=fill,"
            + f"drawtext=text={escaped_title_text}:x={font_size}:y=H-{font_size}-th/2:font=Roboto:fontsize={font_size}:fontcolor=white",
            "-y",
            output_path,
        ],
        verbose=verbose
    )
    return output_path


def collate_videos(path_title_list, file_title, tmp_dir, output_dir, output_ext=".mp4", verbose=False):
    """Collates videos given a list of path-and-title tuples and a file name
    """
    # chapter metadata stuff
    tmp_dir.mkdir(parents=True, exist_ok=True) # ensure dirs
    output_dir.mkdir(parents=True, exist_ok=True) # ensure dirs
    metadata_file_path = tmp_dir / f"{file_title}-metadata.ini"
    metadata_string = ""
    playhead = 0
    processed = []
    max_input_mtime = 0 # maximum modified time for inputs.

    for path, title in path_title_list:   
        try:
            p = process_video(path, title, tmp_dir, verbose=verbose)
        except Exception as e:
            click.secho(f"Processing error: {e}", fg='red')
        try: 
            max_input_mtime = max(max_input_mtime, os.path.getmtime(p)) # update input mtime
            processed.append(p)
            metadata_title = title
            # using a timebase of 1/1000, so multiply seconds by 1000 to get ticks
            ticks = int(float(probe(path)["format"]["duration"])*1000)
            metadata_string += f"""[CHAPTER]
TIMEBASE=1/1000
START={playhead}
END={playhead+ticks}
title={metadata_title}

"""
            playhead += ticks + 1
        except Exception as e:
            click.secho(f"Metadata error: {e}", fg='red')


    with open(metadata_file_path, "w") as mf:
        mf.write(metadata_string)

    if not processed:
        click.secho(f"Collate: No valid videos found, aborting", fg='red')
        return(None)

    else:
        output_path = output_dir / f"{file_title}{output_ext}" # previously had .mkv hardcoded.
        temp_output_path = tmp_dir / f"{file_title}{output_ext}"

        if output_path.exists() and os.path.getmtime(output_path) >= max_input_mtime:
            # don't render again if output newer than all inputs.
            click.secho(f'Skipping {file_title}: already rendered.', fg='green')
            return output_path

        # prepare input args
        input_args = []
        n = len(processed)
        for i in range(n):
            input_args.append("-i")
            input_args.append(processed[i])

        # include the chapters from metadata file
        input_args += ["-i", metadata_file_path, "-map_metadata", "1"]

        # prepare filter string
        filter_string = f"concat=n={n}:v=1:a=1 [v] [a]"
        for i in reversed(range(n)):
            filter_string = f"[{i}:v] [{i}:a] " + filter_string

        # click.secho(input_args, filter_string)
        # it's showtime!
        run_ffmpeg(
            input_args
            + [
                "-filter_complex",
                filter_string,
                "-map",
                "[v]",
                "-map",
                "[a]",
                "-y",
                temp_output_path,
            ]
        )
        ## creating the output in the temp directory and moving it.
        os.rename(temp_output_path, output_path) ## move file to final destination.
        click.secho(f"Processor created video: {output_path}", fg="green")
        return output_path
