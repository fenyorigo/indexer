from app.cli import build_parser


def test_images_only_defaults_to_yes() -> None:
    args = build_parser().parse_args(
        ["--cli", "--db", "/tmp/photos.db", "--media-root", "/tmp/photos"]
    )
    assert args.images_only is True


def test_images_only_can_be_disabled() -> None:
    args = build_parser().parse_args(
        ["--cli", "--db", "/tmp/photos.db", "--media-root", "/tmp/photos", "--images-only", "no"]
    )
    assert args.images_only is False


def test_root_alias_still_parses_media_root() -> None:
    args = build_parser().parse_args(["--cli", "--db", "/tmp/photos.db", "--root", "/tmp/photos"])
    assert str(args.media_root) == "/tmp/photos"


def test_db_media_path_parses() -> None:
    args = build_parser().parse_args(
        [
            "--cli",
            "--db",
            "/tmp/photos.db",
            "--media-root",
            "/mnt/card",
            "--db-media-path",
            "/data/photos",
        ]
    )
    assert str(args.db_media_path) == "/data/photos"
