"""Manual check: render every template's preview so it can be eyeballed.

Replaces the old test/test_collage_strip.py, which still imported libs.collage,
a module that no longer exists.

    python tools/manual/check_templates.py [output_directory]
"""

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from libs.template_collage import load_templates


def main():
    output_directory = Path(sys.argv[1] if len(sys.argv) > 1 else 'template_previews')
    output_directory.mkdir(parents=True, exist_ok=True)

    templates = load_templates('templates')
    for index, template in enumerate(templates):
        preview_path = template.get_preview()
        target = output_directory / f'{index}_{template.get_name().replace(" ", "_")}.jpg'
        shutil.copyfile(preview_path, target)
        print(
            f'{template.get_name():20} {template.get_photos_required()} photo(s)  '
            f'ratio={template.get_aspect_ratio():.3f}  -> {target}'
        )

    print(f'\n{len(templates)} template(s) rendered into {output_directory.resolve()}')


if __name__ == '__main__':
    main()
