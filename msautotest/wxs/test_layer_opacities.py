"""Pixel-level CGI and persistent FastCGI tests, without a web server."""

import concurrent.futures
import io
import os
import shutil
import socket
import struct
import subprocess
from pathlib import Path
from urllib.parse import urlencode

import pytest
from PIL import Image


@pytest.fixture
def server(tmp_path):
    executable = shutil.which(os.environ.get("MAPSERV", "mapserv"))
    if not executable:
        pytest.skip("mapserv executable not available")
    if "SUPPORTS=WMS_SERVER" not in subprocess.check_output(
        [executable, "-v"], text=True
    ):
        pytest.skip("MapServer built without WMS server support")
    mapfile = tmp_path / "opacity.map"
    mapfile.write_text(Path(__file__).with_name("wms_layer_opacities.map").read_text())
    config = tmp_path / "mapserver.conf"
    config.write_text(f'CONFIG MAPS "opacity" "{mapfile}" END END\n')
    env = os.environ.copy()
    env["MAPSERVER_CONFIG_FILE"] = str(config)
    env["MS_WMS_ERROR_STATUS_CODE"] = "ON"
    env.pop("QUERY_STRING", None)
    env.pop("REQUEST_METHOD", None)
    return executable, env, mapfile


def query(opacity=None, **overrides):
    params = dict(
        MAP="opacity",
        SERVICE="WMS",
        VERSION="1.1.1",
        REQUEST="GetMap",
        LAYERS="red,blue",
        STYLES="",
        SRS="EPSG:3857",
        BBOX="0,0,64,64",
        WIDTH="64",
        HEIGHT="64",
        FORMAT="image/png",
    )
    if opacity is not None:
        params["LAYER_OPACITIES"] = opacity
    params.update(overrides)
    return urlencode(params)


def cgi(server, request):
    executable, env, _ = server
    return subprocess.run(
        [executable, "QUERY_STRING=" + request],
        env=env,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
    ).stdout


def image(response):
    # MapServer emits LF headers, but accept CGI's CRLF convention as well.
    separator = b"\r\n\r\n" if b"\r\n\r\n" in response else b"\n\n"
    headers, body = response.split(separator, 1)
    assert b"image/png" in headers, response
    result = Image.open(io.BytesIO(body)).convert("RGB")
    assert result.size == (64, 64)
    return result


def pixel_close(result, x, expected, tolerance=1):
    actual = result.getpixel((x, 32))
    assert all(abs(a - e) <= tolerance for a, e in zip(actual, expected)), actual


def test_multiple_layers_and_styles(server):
    _, _, mapfile = server
    original_mapfile = mapfile.read_bytes()
    baseline_response = cgi(server, query())
    baseline = image(baseline_response)
    pixel_close(baseline, 16, (255, 51, 51))
    pixel_close(baseline, 56, (0, 0, 255))
    faded = image(cgi(server, query("red:40,blue:75")))
    pixel_close(faded, 16, (255, 153, 153))
    pixel_close(faded, 56, (64, 64, 255))
    pixel_close(faded, 40, (64, 38, 230))
    partial = image(cgi(server, query("red:40")))
    assert partial.getpixel((56, 32)) == baseline.getpixel((56, 32))
    assert partial.getpixel((40, 32)) == baseline.getpixel((40, 32))
    transparent = image(cgi(server, query("red:0,blue:0")))
    pixel_close(transparent, 16, (255, 255, 255))
    pixel_close(transparent, 56, (255, 255, 255))
    opaque = image(cgi(server, query("red:100,blue:100")))
    pixel_close(opaque, 16, (255, 0, 0))
    pixel_close(opaque, 56, (0, 0, 255))
    # The black Mapfile outline is still present, not replaced by a new style.
    assert opaque.getpixel((0, 32))[0] < opaque.getpixel((16, 32))[0]
    assert cgi(server, query()) == baseline_response
    assert mapfile.read_bytes() == original_mapfile


@pytest.mark.parametrize("layers", ["colors", "opacity_root"])
def test_group_request_targets_only_named_sublayer(server, layers):
    opacity = "red:40" if layers == "colors" else "red:40,unused:0"
    result = image(cgi(server, query(opacity, LAYERS=layers)))
    pixel_close(result, 16, (255, 153, 153))
    pixel_close(result, 56, (0, 0, 255))


def test_nested_group(server):
    _, _, mapfile = server
    mapfile.write_text(
        mapfile.read_text().replace(
            'GROUP "colors"', 'METADATA "wms_layer_group" "/outer/inner" END'
        )
    )
    result = image(cgi(server, query("red:40", LAYERS="outer")))
    pixel_close(result, 16, (255, 153, 153))
    pixel_close(result, 56, (0, 0, 255))
    assert b"InvalidParameterValue" in cgi(server, query("inner:40", LAYERS="outer"))


@pytest.mark.parametrize("ambiguous", [False, True])
def test_single_child_and_ambiguous_group_rejected(server, ambiguous):
    _, _, mapfile = server
    text = mapfile.read_text().replace('GROUP "colors"', 'GROUP "one_child"', 1)
    if ambiguous:
        text = text.replace('NAME "red"', 'NAME "one_child"', 1)
    mapfile.write_text(text)
    assert b"InvalidParameterValue" in cgi(
        server, query("one_child:40", LAYERS="one_child")
    )


def test_repeated_layer_with_named_styles(server):
    _, _, mapfile = server
    text = mapfile.read_text().replace(
        "CLASS\n      STYLE\n        COLOR 255 0 0",
        'CLASS GROUP "first"\n      STYLE\n        COLOR 255 0 0',
    )
    # Add a second named style to the red layer, without changing the blue one.
    text = text.replace(
        '  END\n  LAYER\n    NAME "blue"',
        '    CLASS GROUP "second" STYLE COLOR 0 255 0 END END\n'
        '  END\n  LAYER\n    NAME "blue"',
        1,
    )
    mapfile.write_text(text)
    result = image(
        cgi(server, query("red:40", LAYERS="red,red", STYLES="first,second"))
    )
    # Integer rounding accumulates across the two compositing passes.
    pixel_close(result, 16, (153, 194, 92), tolerance=2)


@pytest.mark.parametrize("version", ["1.1.1", "1.3.0"])
def test_wms_versions(server, version):
    overrides = dict(VERSION=version)
    if version == "1.3.0":
        overrides["CRS"] = "EPSG:3857"
    result = image(cgi(server, query("red:40", **overrides)))
    pixel_close(result, 16, (255, 153, 153))


def test_namespace_qualified_layer_name(server):
    _, _, mapfile = server
    mapfile.write_text(mapfile.read_text().replace('NAME "red"', 'NAME "ns:red"'))
    result = image(cgi(server, query("ns:red:40", LAYERS="ns:red,blue")))
    pixel_close(result, 16, (255, 153, 153))


def test_disabled_layer(server):
    _, _, mapfile = server
    mapfile.write_text(
        mapfile.read_text().replace(
            'NAME "unused"',
            'NAME "unused" METADATA "wms_enable_request" "!GetMap" END',
        )
    )
    assert b"InvalidParameterValue" in cgi(server, query("unused:40"))


@pytest.mark.parametrize(
    "value",
    [
        "",
        "red:-1",
        "red:101",
        "red:1.5",
        "red:nan",
        "red:inf",
        "red:1e2",
        "red:+40",
        "red: 40",
        "red:99999999999999999999",
        "red:",
        ":40",
        "red",
        "red:40,",
        ",red:40",
        "red:40,,blue:75",
        "red:40,RED:50",
        "unknown:40",
        "colors:40",
        "opacity_root:40",
        "unused:40",
    ],
)
def test_invalid_parameter(server, value):
    response = cgi(server, query(value))
    assert b"InvalidParameterValue" in response
    assert b"LAYER_OPACITIES" in response
    assert b"Status: 400" in response


def test_duplicate_parameter_and_case_insensitivity(server):
    assert b"InvalidParameterValue" in cgi(
        server, query("red:40") + "&layer_opacities=blue:75"
    )
    result = image(
        cgi(server, query().replace("GetMap", "map") + "&layer_opacities=RED%3A40")
    )
    pixel_close(result, 16, (255, 153, 153))


def test_unrequested_default_layer(server):
    _, _, mapfile = server
    mapfile.write_text(
        mapfile.read_text().replace(
            'NAME "unused"\n    TYPE POLYGON\n    STATUS OFF',
            'NAME "unused"\n    TYPE POLYGON\n    STATUS DEFAULT',
        )
    )
    assert b"InvalidParameterValue" in cgi(server, query("unused:40"))
    result = image(cgi(server, query("red:40")))
    pixel_close(result, 56, (0, 0, 255))


def test_multiple_compositors_rejected(server):
    _, _, mapfile = server
    mapfile.write_text(
        mapfile.read_text().replace(
            "OPACITY 80\n    END", "OPACITY 80\n    END\n    COMPOSITE OPACITY 20 END"
        )
    )
    assert b"InvalidParameterValue" in cgi(server, query("red:40"))
    image(cgi(server, query()))


def test_noncompositing_format_rejected(server):
    executable, env, mapfile = server
    if "SUPPORTS=PBF" not in subprocess.check_output(
        [executable, "-v"], env=env, text=True
    ):
        pytest.skip("MapServer built without vector tile support")
    mapfile.write_text(
        mapfile.read_text().replace(
            '  LAYER\n    NAME "red"',
            '  OUTPUTFORMAT NAME "mvt" DRIVER "MVT" '
            'MIMETYPE "application/vnd.mapbox-vector-tile" END\n'
            '  LAYER\n    NAME "red"',
            1,
        )
    )
    response = cgi(server, query("red:40", FORMAT="application/vnd.mapbox-vector-tile"))
    assert b"InvalidParameterValue" in response
    assert b"supporting layer compositing" in response


def record(kind, data=b""):
    return struct.pack("!BBHHBB", 1, kind, 1, len(data), 0, 0) + data


def param(name, value):
    name, value = name.encode(), value.encode()

    def length(n):
        return bytes([n]) if n < 128 else struct.pack("!I", n | 0x80000000)

    return length(len(name)) + length(len(value)) + name + value


def read_exact(connection, size):
    result = b""
    while len(result) < size:
        data = connection.recv(size - len(result))
        assert data, "FastCGI worker closed connection prematurely"
        result += data
    return result


class Worker:
    def __init__(self, server):
        executable, env, _ = server
        if "SUPPORTS=FASTCGI" not in subprocess.check_output(
            [executable, "-v"], env=env, text=True
        ):
            pytest.skip("MapServer built without FastCGI")
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen()
        self.process = subprocess.Popen(
            [executable],
            stdin=self.listener,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

    def request(self, request):
        assert self.process.poll() is None
        with socket.create_connection(self.listener.getsockname(), timeout=20) as sock:
            params = b"".join(
                param(k, v)
                for k, v in dict(
                    REQUEST_METHOD="GET",
                    QUERY_STRING=request,
                    SERVER_NAME="localhost",
                    SERVER_PORT="80",
                    SCRIPT_NAME="/mapserv",
                    SERVER_PROTOCOL="HTTP/1.1",
                ).items()
            )
            sock.sendall(
                record(1, struct.pack("!HB5x", 1, 0))
                + record(4, params)
                + record(4)
                + record(5)
            )
            output, errors = b"", b""
            while True:
                version, kind, request_id, size, padding, _ = struct.unpack(
                    "!BBHHBB", read_exact(sock, 8)
                )
                assert version == 1 and request_id == 1
                data = read_exact(sock, size)
                read_exact(sock, padding)
                if kind == 6:
                    output += data
                elif kind == 7:
                    errors += data
                elif kind == 3:
                    assert struct.unpack("!IB3x", data) == (0, 0), errors
                    break
        assert self.process.poll() is None
        return output

    def close(self):
        self.process.terminate()
        try:
            self.process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.communicate(timeout=5)
        self.listener.close()


def test_reused_fastcgi_workers_and_parallel_isolation(server):
    workers = []
    try:
        workers.append(Worker(server))
        workers.append(Worker(server))
        baseline = workers[0].request(query())
        image(baseline)  # Proves the worker is running and responsive.
        pid = workers[0].process.pid
        assert workers[0].request(query("red:40,blue:75")) != baseline
        assert workers[0].request(query()) == baseline
        assert b"InvalidParameterValue" in workers[0].request(query("red:40,blue:101"))
        assert workers[0].request(query()) == baseline
        assert workers[0].process.pid == pid
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            faded = executor.submit(workers[0].request, query("red:0,blue:0"))
            unchanged = executor.submit(workers[1].request, query())
            pixel_close(image(faded.result()), 16, (255, 255, 255))
            assert unchanged.result() == baseline
        assert workers[0].request(query()) == baseline
        assert workers[1].request(query()) == baseline
    finally:
        for worker in workers:
            worker.close()
