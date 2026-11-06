MapServer
=========

[![Build Status](https://github.com/mapserver/mapserver/actions/workflows/build.yml/badge.svg)](https://github.com/mapserver/mapserver/actions?query=workflow%3A%22build%22+branch%3Amain)
[![Appveyor Build Status](https://ci.appveyor.com/api/projects/status/vw1n07095a8bg23u?svg=true)](https://ci.appveyor.com/project/mapserver/mapserver)
[![Coveralls Status](https://coveralls.io/repos/github/MapServer/MapServer/badge.svg?branch=main)](https://coveralls.io/github/MapServer/MapServer?branch=main)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.6994443.svg)](https://doi.org/10.5281/zenodo.6994443)
[![Release](https://img.shields.io/github/v/release/MapServer/MapServer)](https://github.com/MapServer/MapServer/releases)

-------
Summary
-------
   
MapServer is a system for developing web-based GIS applications. 
The basic system consists of a CGI program that can be configured to 
respond to a variety of spatial requests like making maps, scalebars, 
and point, area and feature queries. Virtually all aspects of an 
application, from web interface to map appearance can be developed 
without any programming. For the more ambitious user, MapServer 
applications can be enhanced using Python, PHP, Java, JavaScript or 
many other web technologies. For more  information and complete 
documentation please visit:

  https://mapserver.org/

Bug reports and enhancement submissions can be reported in the MapServer 
issue tracker at the following url.   If you do make changes and/or enhancements, 
please let us know so that they might be incorporated into future releases.

  https://github.com/MapServer/MapServer/issues


Join the MapServer user mailing list online at:

  https://mapserver.org/community/lists.html

Credits
-------

MapServer was originally written by Stephen Lime. Major funding for development of 
MapServer has been provided by NASA through cooperative argreements with 
the University of Minnesota, Department of Forest Resources.

PHP/MapScript developed by DM Solutions Group.

GDAL/OGR support and significant WMS support provided by DM Solutions Group 
which received funding support from Canadian Government's GeoConnections 
Program and the Canadian Forest Service.

Raster support developed by Pete Olson of the State of Minnesota, Land 
Management Information Center, and maintained by Frank Warmerdam (DM 
Solutions).

PostGIS spatial database support provided by Dave Blasby of Refractions 
Research.

PDF support developed by Jeff Spielberg and Jamie Wall of Market Insite Group, 
Inc.

OracleSpatial support developed by Rodrigo Cabral of CTTMAR/UNIVALI, Brazil.

Portions Copyright (c) 1998 State of Minnesota, Land Management Information 
Center.

Portions derived from Shapelib, Copyright 1995-1999 Frank Warmerdam.

Supporting packages are covered by their own copyrights.

License
-------

See [LICENSE.md](LICENSE.md)

Security policy
---------------

See [SECURITY.md](SECURITY.md)

How to Contribute
-----------------

See [CONTRIBUTING.md](CONTRIBUTING.md)

Documentation Repository
------------------------

Use the separate [MapServer-documentation](https://github.com/MapServer/MapServer-documentation) 
repository for filing documentation tickets and changes.

WMS GetMap layer opacity extension
---------------------------------

The vendor-specific GetMap parameter `LAYER_OPACITIES` sets
request-local layer opacity without replacing Mapfile classes, symbols or
styles. For example, a single request can render two layers together:

```text
SERVICE=WMS&VERSION=1.1.1&REQUEST=GetMap&LAYERS=roads,buildings&STYLES=&SRS=EPSG:3857&BBOX=0,0,1000,1000&WIDTH=256&HEIGHT=256&FORMAT=image/png&LAYER_OPACITIES=roads:40,buildings:75
```

The format is a comma-separated list of `layer-name:opacity` pairs, using
the advertised WMS layer names, not positional entries for expanded groups.
The last colon separates the value, so namespace-qualified names are supported.
URL-encode names and delimiters as usual; names containing commas cannot be
represented. Parameter and layer names are case-insensitive, as in `LAYERS`.
Each layer may occur only once in this parameter.

Values are decimal integers from **0** (invisible) to **100** (opaque), with
at most three digits, without signs, whitespace, fractions or exponents.
The supplied value overrides the layer's existing compositing opacity; it
does not multiply it. Unspecified layers retain their Mapfile opacity and
symbolization. Omitting the parameter leaves existing behavior unchanged.
The accompanying renderer error-handling correction ensures that failed
layer rendering is no longer hidden by successful buffer compositing,
including for existing requests without this parameter.

An explicit, non-empty `LAYERS` parameter is required. A target must be an
enabled individual WMS layer selected by `LAYERS`, either directly or through
a requested group/root. Group and root names are not opacity targets, even
when a group contains only one layer. Unknown, disabled or unrequested targets
(including automatically drawn `STATUS DEFAULT` layers not selected by
`LAYERS`) are errors, not ignored entries. Render copies created by repeated
layer names with different `STYLES` receive the same opacity.

This uses `msSetLayerOpacity()` and the existing layer compositor, preserving
classes, styles, compositing operators and filters. As with Mapfile layer
compositing, cached labels drawn separately from the layer are not faded.
Output formats must support layer compositing (for example AGG/PNG);
vector-tile and other non-compositing outputs are rejected. Layers with
multiple `COMPOSITE` blocks are rejected because this API controls only the
first block and would not provide a layer-wide override.

Empty/malformed lists, invalid values, duplicate parameter occurrences or
targets, and unsupported targets/compositing produce a WMS
`InvalidParameterValue` ServiceException through the usual WMS exception
handling (`EXCEPTIONS` and `MS_WMS_ERROR_STATUS_CODE`, HTTP 400 when enabled).
The complete list is validated before any opacity is applied.
Standard WMS parameter validation still takes precedence, for example
`MissingParameterValue` or `LayerNotDefined` for invalid `LAYERS`.
The extension applies only to GetMap (including the legacy `REQUEST=map`);
other WMS operations continue to ignore this vendor parameter.

Overrides are scoped to GetMap rendering and restored on every exit, including
render errors, so even callers reusing a MapScript map object retain its
previous opacity. CGI/FastCGI additionally load and free a map for each
request. There are no new global settings, metadata requirements, external
dependencies or uses of `SLD_BODY`. Applications must still avoid concurrent
dispatch on the *same* mutable map object, as required by the existing API.

Tests: CMake/CTest `wms_opacity_test` checks API/style preservation, reused maps
and error cleanup. `pytest msautotest/wxs/test_layer_opacities.py` checks actual
PNG pixels, validation, groups and successive/concurrent requests to real
FastCGI workers. Set `MAPSERV` to the built executable if it is not on `PATH`;
FastCGI-specific tests skip when that support is not built.