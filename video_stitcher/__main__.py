"""
This program stitches lots of videos together with title cards in between.
The title data is sourced from a file.
"""
import csv
import click
from pathlib import Path
import video_stitcher.ffmpeg as ffmpeg


base_path = Path("videos")
inputs_path = base_path / "inputs"
tmp_path = base_path / "tmp"
save_path = base_path / "output"
video_fileexts = [".mp4", ".mkv", ".mov", ".flv", ".m4v", ".wmv"]
data_path = Path("data")


def load_data(datafile="data.csv"):
    with open(data_path / datafile, newline='') as csvfile:
      data_list = list(csv.DictReader(csvfile))
    # format,presence
    # poster,remote,
    data_list = [row for row in data_list if row['format'] == 'poster' and row['presence'] == 'remote']
    # data_list = [row for row in data_list if row['presence'] == 'remote']
    return data_list

def create_directories():
    """
    Creates the submissions, tmp and output directories if they don't exist.
    """
    paths = [inputs_path, tmp_path, save_path]
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)


def video_path(video_id, verbose=False):
    """
    Finds the video for a given ID.
    assuming the video is in the videos/inputs dir and called {id}.mp4/mkv/mov etc.
    """
    for ext in video_fileexts:
        p = inputs_path / f"{video_id}{ext}"
        if p.exists():
            return p
        else:
            if verbose:
                click.secho(f"ID {video_id}: no video found!", fg='red')
            return None


id_col = "id"
title_col = "title"
authors_col = "authors-names"
session_col = "session_code"


def build_video_lists():
  data = load_data()
  sessions = {row[session_col] for row in data} # set of sessions
  click.secho(f"Sessions {sessions}", fg="blue")
  video_dict = {}
  for s in sessions:
    click.secho(f"Finding video for {s}.", fg="yellow")
    video_list = [(video_path(entry[id_col]), entry[title_col], entry[authors_col]) for entry in data if entry[session_col] == s]
    video_list = [(path, title, authors) for (path, title, authors) in video_list if path is not None]
    video_dict[s] = video_list   
    click.secho(f"{s}: {video_list}", fg="yellow")     
    return video_dict


@click.command(name="render")
@click.option('--verbose', is_flag=True, default=True, help='Print out more information.')
def render(verbose=True):
    """Collates and renders all videos.
    """
    create_directories()
    click.secho(f"Build the video lists.", fg='green')
    video_dict = build_video_lists()
    click.secho("Going to collate the videos.", fg="blue")
    # video_dict has the structure:
    # {session_name: [(path, title, authors), (path, title, authors),...], ...}
    rendered_videos = []
    for session, video_list in video_dict.items():
        video_path = ffmpeg.collate_videos(video_list, f"video_{session}", tmp_path, save_path, verbose=verbose)
        if video_path is not None:
            rendered_videos.append(video_path)
    click.secho(f"Render: created these videos:\n{rendered_videos}", fg="green")


if __name__ == '__main__':
    render() ## simple use of click with one command
