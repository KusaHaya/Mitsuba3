"""Build a physically sized PMMA lens scene and measure one LCD patch."""
import argparse
import json
from pathlib import Path
import numpy as np
from optics import OpticsConfig, lens_coordinates, make_scene


def write_binary_ply(path, vertices, faces):
    # Simple ASCII PLY allows the geometry to be inspected separately.
    with open(path, "w", encoding="ascii") as f:
        f.write("ply\nformat ascii 1.0\n")
        f.write(f"element vertex {len(vertices)}\n")
        f.write("property float x\nproperty float y\nproperty float z\n")
        f.write(f"element face {len(faces)}\n")
        f.write("property list uchar int vertex_indices\nend_header\n")
        for p in vertices:
            f.write(f"{p[0]:.9g} {p[1]:.9g} {p[2]:.9g}\n")
        for tri in faces:
            f.write(f"3 {tri[0]} {tri[1]} {tri[2]}\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", type=int, choices=range(4), default=0)
    parser.add_argument("--spp", type=int, default=128)
    parser.add_argument("--variant", default="llvm_ad_rgb")
    parser.add_argument("--output", type=Path, default=Path("results"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    cfg = OpticsConfig()
    vertices, faces = lens_coordinates(cfg)
    ply_path = args.output / "lenticular.ply"
    write_binary_ply(ply_path, vertices, faces)

    import mitsuba as mi
    mi.set_variant(args.variant)
    scene = mi.load_dict(make_scene(cfg, args.phase, ply_path, args.spp))
    image = mi.render(scene, spp=args.spp)
    image_array = np.asarray(image)
    value = float(image_array.ravel()[0])
    mi.util.write_bitmap(str(args.output / f"phase_{args.phase}.exr"), image)
    result = {
        "phase": args.phase, "spp": args.spp, "variant": args.variant,
        "irradiance_patch_reading": value,
        "measurement": "one irradiancemeter patch, not an LCD irradiance map",
        "config": vars(cfg),
    }
    (args.output / f"phase_{args.phase}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
