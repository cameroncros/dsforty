**dsforty** talks to Epson DS-40 scanner and scans a page outputting the
image in JPEG format with quality of 100. Since the scanner sports an
Automatic Document Feeder (ADF), it's easy to determine the height of
the scanned document and crop it accordingly, which *dsforty* does
losslessly with help of [jpegtran][]. However, the width of the image is
a bit tricky to get right. As of now, if Python PIL is installed,
*dsforty* uses a simple technique to figure out the vertical borders and
trims it using jpegtran.

To scan, hook up DS-40 to USB, put the slider to USB mode as well and
run:

    ./dsforty.py > image.jpeg

For now, you can only set color mode and resolution. Run with `-h` to
find out how.

[jpegtran]: http://jpegclub.org/jpegtran/
