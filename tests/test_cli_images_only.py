from app.cli import build_parser


def test_images_only_defaults_to_yes() -> None:
    args = build_parser().parse_args(["--cli", "--db", "/tmp/photos.db", "--root", "/tmp/photos"])
    assert args.images_only is True


def test_images_only_can_be_disabled() -> None:
    args = build_parser().parse_args(
        ["--cli", "--db", "/tmp/photos.db", "--root", "/tmp/photos", "--images-only", "no"]
    )
    assert args.images_only is False
