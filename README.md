# aspose-tex

Pure-Python library for TeX/LaTeX processing. Parses TeX input and produces PDF,
SVG, and DVI output. No external TeX installation required — Computer Modern
fonts and hyphenation patterns are bundled.

> **Status: Pre-Alpha.** The core engine and public API are under active
> development. Interfaces may change between releases.

## Requirements

- Python 3.10+

## Installation

```bash
pip install aspose-tex
```

For development:

```bash
pip install -e ".[dev]"
```

## Quick Start

### PDF output

```python
from pathlib import Path
from aspose_tex import TeXJob, TeXOptions, PdfDevice, create_input_source

source = create_input_source("Hello World\n\\bye")
device = PdfDevice(Path("hello.pdf"))
job = TeXJob(source, device, options=TeXOptions(load_format=False))
job.run() # hello.pdf is written to disk
```

In-memory PDF:

```python
from aspose_tex import TeXJob, TeXOptions, PdfDevice, create_input_source

source = create_input_source("Hello World\n\\bye")
device = PdfDevice()
job = TeXJob(source, device, options=TeXOptions(load_format=False))
pdf_bytes = job.run()
```

### DVI output

```python
from aspose_tex import TeXJob, TeXOptions, DviDevice, create_input_source

source = create_input_source("Hello World\n\\bye")
device = DviDevice()
job = TeXJob(source, device, options=TeXOptions(load_format=False))
dvi_bytes = job.run()
```

Output to file directly:

```python
from pathlib import Path
from aspose_tex import TeXJob, TeXOptions, DviDevice, create_input_source

source = create_input_source("Hello World\n\\bye")
device = DviDevice(Path("hello.dvi"))
job = TeXJob(source, device, options=TeXOptions(load_format=False))
job.run() # returns None; output is on disk
```

### SVG output

```python
from aspose_tex import TeXJob, TeXOptions, SvgDevice, create_input_source

source = create_input_source("Hello World\n\\bye")
device = SvgDevice()
job = TeXJob(source, device, options=TeXOptions(load_format=False))
svg_bytes = job.run() # UTF-8 encoded SVG 1.1 document
```

Output to file:

```python
from pathlib import Path
from aspose_tex import TeXJob, TeXOptions, SvgDevice, create_input_source

source = create_input_source("Hello World\n\\bye")
device = SvgDevice(Path("output/hello"))
job = TeXJob(source, device, options=TeXOptions(load_format=False))
job.run() # writes output/hello.svg (or hello-1.svg, hello-2.svg for multi-page)
```

Multi-page in-memory output:

```python
from aspose_tex import TeXJob, TeXOptions, SvgDevice, create_input_source

source = create_input_source("Page one\n\\eject\nPage two\n\\bye")
device = SvgDevice()
job = TeXJob(source, device, options=TeXOptions(load_format=False))
job.run()
pages = device.get_all_pages() # list[bytes], one SVG per page
```

SVG output is self-contained — glyph outlines are extracted from the bundled
Computer Modern PFB fonts and embedded as `<path>` elements, so no external
fonts are required by the SVG viewer.

### Options

```python
from aspose_tex import TeXJob, TeXOptions, PdfDevice, create_input_source

opts = TeXOptions(job_name="hello", magnification=1200, load_format=False)
source = create_input_source("Hello World\n\\bye")
device = PdfDevice()
job = TeXJob(source, device, options=opts)
pdf_bytes = job.run()
```

### Messages and logging

`TeXJob.messages` returns a copy of the messages collected during the most
recent run. `\message` and `\write 16` append plain-text messages; `\errmessage`
appends messages with a leading `! ` prefix; `\write -1` logs only.

```python
from pathlib import Path
from aspose_tex import TeXJob, TeXOptions, DviDevice, create_input_source

opts = TeXOptions(load_format=False, extra_format_paths=[Path("tex-inputs")])
source = create_input_source("\\input chapter1\n\\bye")
job = TeXJob(source, DviDevice(), options=opts)
dvi_bytes = job.run()
messages = job.messages
```

`extra_format_paths` is searched after bundled format data and before the
current working directory for `\input` files.

The package registers a `logging.NullHandler` on the `aspose_tex` logger so
applications can opt into standard Python logging without receiving default
handler warnings:

```python
import logging

logging.basicConfig(level=logging.INFO)
logging.getLogger("aspose_tex").setLevel(logging.INFO)
```

## License

Released under the MIT License — see [LICENSE](LICENSE). Bundled Computer Modern
fonts are covered separately — see [LICENSE-FONTS](LICENSE-FONTS).
