import asyncio
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional
import boto3
from botocore.config import Config
from .base import BaseTranscoder, TranscodeJob, TranscodeResult, VideoMetadata


def parse_probe_metadata(data: dict) -> Optional[VideoMetadata]:
    """Parse ffprobe JSON (-show_streams -show_format) into VideoMetadata.

    Returns None when there is no video stream. Guards r_frame_rate "0/0"
    (fps stays 0.0 — never fabricate a rate) and falls back to format-level
    duration when the stream lacks one (common for MKV/WebM).
    """
    streams = data.get("streams") or []
    if not streams:
        return None
    stream = streams[0]
    fps = 0.0
    raw_rate = stream.get("r_frame_rate") or ""
    if "/" in raw_rate:
        num, _, den = raw_rate.partition("/")
        try:
            if float(den) != 0:
                fps = float(num) / float(den)
        except ValueError:
            fps = 0.0
    duration = float(stream.get("duration") or 0)
    if not duration:
        duration = float((data.get("format") or {}).get("duration") or 0)
    return VideoMetadata(
        duration_seconds=duration,
        width=int(stream.get("width") or 0),
        height=int(stream.get("height") or 0),
        fps=fps,
    )


class FFmpegTranscoder(BaseTranscoder):
    def __init__(self, s3_client, bucket: str, s3_endpoint: str = None):
        self.s3 = s3_client
        self.bucket = bucket
        self.s3_endpoint = s3_endpoint
    
    def _get_presigned_url(self, s3_key: str, expires_in: int = 7200) -> str:
        """Generate a presigned URL for streaming input to FFmpeg."""
        return self.s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": s3_key},
            ExpiresIn=expires_in,
        )

    @staticmethod
    def _run(cmd: list[str], timeout: int | None = None, label: str = "ffmpeg") -> str:
        """Run a command, raising RuntimeError with stderr on failure.

        Uses errors='replace' because ffmpeg often echoes input metadata
        (Latin-1 / Shift-JIS) to stderr, which would break strict UTF-8 decode.
        """
        result = subprocess.run(
            cmd, capture_output=True, text=True, errors='replace', timeout=timeout,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            raise RuntimeError(
                f"{label} exited {result.returncode}: {stderr or 'no stderr output'}"
            )
        return result.stdout

    @staticmethod
    def _write_master_playlist(hls_dir: Path, qualities: list[str], quality_map: dict) -> None:
        """Overwrite hls_dir/master.m3u8 with #EXT-X-STREAM-INF entries built
        from what we asked ffmpeg to encode (rendition index -> quality),
        rather than trusting ffmpeg's own master playlist output - see the
        call site for why."""
        lines = ["#EXTM3U", "#EXT-X-VERSION:6"]
        for i, q in enumerate(qualities):
            width, height = quality_map[q][0].split(":")
            variant_dir = hls_dir / str(i)

            total_bytes = sum(f.stat().st_size for f in variant_dir.glob("*.ts"))
            total_seconds = 0.0
            playlist_path = variant_dir / "playlist.m3u8"
            if playlist_path.exists():
                for line in playlist_path.read_text().splitlines():
                    if line.startswith("#EXTINF:"):
                        total_seconds += float(line[len("#EXTINF:"):].split(",")[0])
            bandwidth = int((total_bytes * 8) / total_seconds) if total_seconds > 0 else 500_000

            lines.append(
                f"#EXT-X-STREAM-INF:BANDWIDTH={bandwidth},AVERAGE-BANDWIDTH={bandwidth},RESOLUTION={width}x{height}"
            )
            lines.append(f"{i}/playlist.m3u8")
        (hls_dir / "master.m3u8").write_text("\n".join(lines) + "\n")

    @staticmethod
    def _fix_rendition_target_durations(hls_dir: Path, qualities: list[str]) -> None:
        """Per the HLS spec, EXT-X-TARGETDURATION must be a positive integer
        (the ceiling of the longest segment). ffmpeg's HLS muxer writes it as
        the *rounded* longest segment duration instead - for any source clip
        under ~1.5s (the whole thing fits in one #EXTINF), that rounds to 0.
        HLS.js/browsers treat TARGETDURATION:0 as malformed and refuse to
        play the rendition, even though every segment file itself is fine -
        same root cause as _write_master_playlist's fixup above (see its
        call site), just surfacing on the per-rendition playlists instead of
        the master one. Only ever raises the value, never lowers it, so
        normal-length clips (already >= 1) are untouched."""
        for i in range(len(qualities)):
            playlist_path = hls_dir / str(i) / "playlist.m3u8"
            if not playlist_path.exists():
                continue
            text = playlist_path.read_text()
            fixed = re.sub(
                r"#EXT-X-TARGETDURATION:(\d+)",
                lambda m: "#EXT-X-TARGETDURATION:" + str(max(1, int(m.group(1)))),
                text,
            )
            if fixed != text:
                playlist_path.write_text(fixed)

    async def get_video_metadata(self, s3_key: str) -> VideoMetadata:
        """Get video metadata using streaming (no full download)."""
        input_url = self._get_presigned_url(s3_key)
        cmd = [
            "ffprobe", "-v", "error", "-print_format", "json",
            "-show_streams", "-select_streams", "v:0", "-show_format", input_url,
        ]
        stdout = self._run(cmd, timeout=120, label="ffprobe")
        meta = parse_probe_metadata(json.loads(stdout))
        if meta is None:
            raise RuntimeError(f"No video stream found in {s3_key}")
        return meta

    async def generate_thumbnails(self, s3_key: str, count: int) -> list[str]:
        """Generate thumbnails at 1 per 10 seconds using streaming input."""
        input_url = self._get_presigned_url(s3_key)
        thumb_dir = tempfile.mkdtemp()
        try:
            cmd = [
                "ffmpeg", "-i", input_url,
                "-vf", "fps=0.1",
                "-q:v", "2",
                f"{thumb_dir}/thumb_%04d.jpg",
            ]
            self._run(cmd, timeout=600, label="ffmpeg")
            return [str(p) for p in sorted(Path(thumb_dir).glob("thumb_*.jpg"))]
        finally:
            shutil.rmtree(thumb_dir, ignore_errors=True)

    async def generate_waveform(self, s3_key: str) -> dict:
        """Generate waveform data for audio visualization using streaming."""
        input_url = self._get_presigned_url(s3_key)
        # Simplified waveform: just return peak data (full waveform extraction is complex)
        return {"samples": [], "peak": 1.0, "source": s3_key}

    async def transcode(self, job: TranscodeJob) -> TranscodeResult:
        """
        Transcode video using streaming input from S3.
        FFmpeg reads directly from presigned URL - no full download needed.
        Only output files are written to disk, reducing disk usage by ~2/3.
        """
        work_dir = Path(tempfile.mkdtemp(prefix=f"transcode_{job.version_id}_"))
        
        # Generate presigned URL for streaming input (2 hour expiry for large files)
        input_url = self._get_presigned_url(job.input_s3_key, expires_in=7200)

        try:
            # 1. Get video metadata via streaming (no download)
            cmd = [
                "ffprobe", "-v", "error", "-print_format", "json",
                "-show_streams", "-select_streams", "v:0", "-show_format", input_url,
            ]
            vid_info = self._run(cmd, timeout=120, label="ffprobe")
            meta = parse_probe_metadata(json.loads(vid_info))

            # 2. Check if input has an audio stream
            audio_cmd = [
                "ffprobe", "-v", "error", "-print_format", "json",
                "-show_streams", "-select_streams", "a", input_url,
            ]
            audio_result = self._run(audio_cmd, timeout=120, label="ffprobe")
            has_audio = bool(json.loads(audio_result).get("streams"))

            # 3. Build quality ladder based on available qualities
            QUALITY_MAP = {
                "1080p": ("1920:1080", 20),
                "720p": ("1280:720", 22),
                "360p": ("640:360", 26),
            }
            # qualities = [q for q in job.qualities if q in QUALITY_MAP]
            requested = [q for q in job.qualities if q in QUALITY_MAP]
            source_height = meta.height if meta else 0

            qualities = [
                q for q in requested
                if int(QUALITY_MAP[q][0].split(":")[1]) <= source_height
            ]
            if not qualities and requested:
                qualities = [min(requested, key=lambda q: int(QUALITY_MAP[q][0].split(":")[1]))]
            hls_dir = work_dir / "hls"
            hls_dir.mkdir()

            # Build filter_complex and map args
            # Use force_original_aspect_ratio=decrease to preserve aspect ratio,
            # then pad to even dimensions required by libx264
            split_outputs = "".join(f"[v{i}]" for i in range(len(qualities)))
            filter_complex = f"[v:0]split={len(qualities)}{split_outputs};"
            filter_complex += ";".join(
                f"[v{i}]scale={QUALITY_MAP[q][0]}:force_original_aspect_ratio=decrease,pad=ceil(iw/2)*2:ceil(ih/2)*2[{q}]"
                for i, q in enumerate(qualities)
            )

            ffmpeg_cmd = [
                "ffmpeg", "-y", "-i", input_url,
                "-filter_complex", filter_complex,
            ]

            for i, quality in enumerate(qualities):
                scale, crf = QUALITY_MAP[quality]
                ffmpeg_cmd += ["-map", f"[{quality}]"]
                if has_audio:
                    ffmpeg_cmd += ["-map", "a:0"]
                ffmpeg_cmd += [
                    f"-c:v:{i}", "libx264", f"-crf", str(crf), "-preset", "fast",
                    "-force_key_frames", "expr:gte(t,n_forced*2)",
                ]

            # .as_posix(), not str(): ffmpeg's HLS muxer writes the master
            # playlist's per-quality variant references (e.g. "0/playlist.m3u8")
            # by reusing whatever separator convention the *command-line* path
            # arguments used - str(Path) is OS-native, so on Windows this
            # silently baked literal backslashes ("0\playlist.m3u8") into the
            # master.m3u8 content itself. Browsers/HLS.js parse "\" as part of
            # the filename, not a path separator, so playback failed even
            # though every individual file uploaded fine. ffmpeg accepts "/"
            # in paths on Windows too, so this is safe for the actual file I/O
            # as well as the muxer's internal references.
            ffmpeg_cmd += [
                "-f", "hls",
                "-hls_time", "2",
                "-hls_playlist_type", "vod",
                "-hls_flags", "independent_segments",
                "-hls_segment_type", "mpegts",
                "-master_pl_name", "master.m3u8",
                "-var_stream_map", " ".join(
                    f"v:{i},a:{i}" if has_audio else f"v:{i}"
                    for i in range(len(qualities))
                ),
                "-hls_segment_filename", (hls_dir / "%v" / "seg_%03d.ts").as_posix(),
                (hls_dir / "%v" / "playlist.m3u8").as_posix(),
            ]

            # Create per-quality directories
            for q in qualities:
                (hls_dir / q).mkdir(exist_ok=True)

            # Timeout scales with expected duration - 4 hours for very large files
            self._run(ffmpeg_cmd, timeout=14400, label="ffmpeg")

            # ffmpeg's own HLS muxer can silently write master.m3u8 with just
            # the bare "#EXTM3U/#EXT-X-VERSION" header and none of the
            # #EXT-X-STREAM-INF variant lines - reproduced locally with any
            # sub-1-second source clip (TARGETDURATION:0 on the rendition
            # playlists is the tell). ffmpeg still exits 0 and every rendition
            # playlist/segment is written correctly, so this was silently
            # invisible on the backend - it only surfaced as HLS.js's fatal
            # networkError in the browser, since a master playlist with zero
            # variants has nothing for it to load. Rewriting master.m3u8
            # ourselves from what we know we asked ffmpeg to produce sidesteps
            # that muxer bug for short clips without changing behavior for
            # normal-length ones.
            self._write_master_playlist(hls_dir, qualities, QUALITY_MAP)
            self._fix_rendition_target_durations(hls_dir, qualities)

            # 4. Upload HLS files to S3
            uploaded_keys = []
            for f in hls_dir.rglob("*"):
                if f.is_file():
                    # S3 keys always use "/" regardless of host OS; Path.__str__ uses
                    # the native separator, so on Windows this silently produced keys
                    # like ".../0\playlist.m3u8" - S3/MinIO reject those outright
                    # (XMinioInvalidObjectName), which made every HLS video transcode
                    # fail on Windows with no output beyond the raw upload error.
                    relative = f.relative_to(hls_dir).as_posix()
                    s3_key = f"{job.output_s3_prefix}/{relative}"
                    content_type, cache_control = self._get_content_type(f.name)
                    self.s3.upload_file(
                        str(f), self.bucket, s3_key,
                        ExtraArgs={"ContentType": content_type, "CacheControl": cache_control},
                    )
                    uploaded_keys.append(s3_key)

            # 5. Generate and upload thumbnail (using streaming URL)
            #
            # -ss <offset> -frames:v 1, not "-vf fps=0.1 -frames:v 1": fps=0.1
            # samples one frame every 10s, so any clip under ~10s (like this
            # 4.2s test delivery) produced zero output frames - "no thumbnail",
            # not an error, just a silently missing image. Seeking directly to
            # a fraction of the real (probed) duration works at any length.
            #
            # -pix_fmt yuvj420p: without it, mjpeg's frame-threaded encoder
            # flatly refuses ambiguous-range yuv420p input ("Non full-range
            # YUV is non-standard" -> "ff_frame_thread_encoder_init failed" ->
            # exit -22 / EINVAL), which previously failed the *entire* asset
            # (HLS included) even though the actual video transcode succeeded.
            duration = (meta.duration_seconds if meta else 0) or 0
            seek_offset = min(1.0, duration / 2) if duration > 0 else 0
            thumb_path = work_dir / "thumb_0001.jpg"
            thumb_cmd = [
                "ffmpeg", "-y", "-ss", str(seek_offset), "-i", input_url,
                "-pix_fmt", "yuvj420p", "-q:v", "2", "-frames:v", "1",
                str(work_dir / "thumb_%04d.jpg"),
            ]
            self._run(thumb_cmd, label="ffmpeg")
            thumbnail_key = f"{job.output_s3_prefix}/thumbnail.jpg"
            if thumb_path.exists():
                self.s3.upload_file(
                    str(thumb_path), self.bucket, thumbnail_key,
                    ExtraArgs={"ContentType": "image/jpeg", "CacheControl": "max-age=86400"},
                )

            return TranscodeResult(
                success=True,
                hls_prefix=job.output_s3_prefix,
                thumbnail_keys=[thumbnail_key],
                duration_seconds=(meta.duration_seconds or None) if meta else None,
                width=(meta.width or None) if meta else None,
                height=(meta.height or None) if meta else None,
                fps=(meta.fps or None) if meta else None,
            )

        except Exception as e:
            return TranscodeResult(success=False, error=str(e))
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    @staticmethod
    def _get_content_type(filename: str) -> tuple[str, str]:
        ext = Path(filename).suffix.lower()
        MAP = {
            ".m3u8": ("application/vnd.apple.mpegurl", "no-cache"),
            ".ts": ("video/mp2t", "max-age=31536000"),
            ".jpg": ("image/jpeg", "max-age=86400"),
        }
        return MAP.get(ext, ("application/octet-stream", "no-cache"))
