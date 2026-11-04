#include "../../src/mapserver.h"
#include "../../src/maperror.h"
#include "../../src/mapio.h"
#include "../../src/mapows.h"
#include "../../src/maptemplate.h"

#include <string>
#include <vector>

static int failures = 0;

#define CHECK(condition)                                                       \
  do {                                                                         \
    if (!(condition)) {                                                        \
      fprintf(stderr, "%s:%d: %s\n", __FILE__, __LINE__, #condition);          \
      failures++;                                                              \
    }                                                                          \
  } while (0)

static mapObj *createMap() {
  char mapfile[] =
      "MAP NAME 'root' SIZE 64 64 EXTENT 0 0 64 64 "
      "PROJECTION 'EPSG:3857' END "
      "WEB METADATA 'wms_title' 'Opacity test' 'wms_srs' 'EPSG:3857' "
      "'wms_enable_request' '*' END END "
      "OUTPUTFORMAT NAME 'png' DRIVER 'AGG/PNG' MIMETYPE 'image/png' "
      "IMAGEMODE RGB END "
      "LAYER NAME 'red' GROUP 'colors' TYPE POLYGON STATUS OFF "
      "COMPOSITE OPACITY 80 COMPOP multiply END "
      "FEATURE POINTS 0 0 48 0 48 64 0 64 0 0 END END "
      "CLASS STYLE COLOR 255 0 0 OUTLINECOLOR 0 0 0 WIDTH 2 OPACITY 60 END END "
      "END "
      "LAYER NAME 'blue' GROUP 'colors' TYPE POLYGON STATUS OFF "
      "FEATURE POINTS 32 0 64 0 64 64 32 64 32 0 END END "
      "CLASS STYLE COLOR 0 0 255 END END END END";
  return msLoadMapFromString(mapfile, nullptr, nullptr);
}

static std::string dispatch(mapObj *map, const char *opacity,
                            int expectedStatus, const char *layers = "colors",
                            const char *styles = "") {
  std::vector<std::string> names = {"SERVICE", "VERSION", "REQUEST", "LAYERS",
                                    "STYLES",  "SRS",     "BBOX",    "WIDTH",
                                    "HEIGHT",  "FORMAT"};
  std::vector<std::string> values = {"WMS",  "1.1.1",     "GetMap",    layers,
                                     styles, "EPSG:3857", "0,0,64,64", "64",
                                     "64",   "image/png"};
  if (opacity) {
    names.emplace_back("LAYER_OPACITIES");
    values.emplace_back(opacity);
  }
  std::vector<char *> namePointers, valuePointers;
  for (auto &name : names)
    namePointers.push_back(name.data());
  for (auto &value : values)
    valuePointers.push_back(value.data());
  cgiRequestObj request{};
  request.type = MS_GET_REQUEST;
  request.NumParams = static_cast<int>(names.size());
  request.ParamNames = namePointers.data();
  request.ParamValues = valuePointers.data();

  msResetErrorList();
  msIO_installStdoutToBuffer();
  const int status = msOWSDispatch(map, &request, OWS);
  if (status != expectedStatus) {
    fprintf(stderr, "opacity=%s: expected status %d, got %d\n",
            opacity ? opacity : "(omitted)", expectedStatus, status);
  }
  CHECK(status == expectedStatus);
  const auto *buffer =
      static_cast<const msIOBuffer *>(msIO_getHandler(stdout)->cbData);
  std::string output(reinterpret_cast<const char *>(buffer->data),
                     buffer->data_offset);
  msIO_resetHandlers();
  return output;
}

static void testAPI() {
  mapObj *map = createMap();
  CHECK(map != nullptr);
  if (!map)
    return;
  layerObj *red = GET_LAYER(map, 0);
  styleObj *style = red->_class[0]->styles[0];
  LayerCompositer *compositer = red->compositer;
  msSetLayerOpacity(red, 40);
  CHECK(red->compositer == compositer && compositer->opacity == 40);
  CHECK(compositer->comp_op == MS_COMPOP_MULTIPLY);
  CHECK(red->_class[0]->styles[0] == style);
  CHECK(style->color.red == 255 && style->outlinecolor.red == 0 &&
        style->width == 2 && style->opacity == 60);
  msFreeMap(map);
}

static void testReusedMap() {
  mapObj *map = createMap();
  CHECK(map != nullptr);
  if (!map)
    return;
  layerObj *red = GET_LAYER(map, 0);
  layerObj *blue = GET_LAYER(map, 1);
  classObj *cls = red->_class[0];
  styleObj *style = cls->styles[0];
  LayerCompositer *compositer = red->compositer;
  const std::string baseline = dispatch(map, nullptr, MS_SUCCESS);
  const std::string faded = dispatch(map, "red:40,blue:75", MS_SUCCESS);
  CHECK(faded != baseline);
  CHECK(red->compositer == compositer && compositer->opacity == 80);
  CHECK(compositer->comp_op == MS_COMPOP_MULTIPLY);
  CHECK(blue->compositer == nullptr);
  CHECK(red->_class[0] == cls && cls->styles[0] == style);
  CHECK(style->color.red == 255 && style->outlinecolor.red == 0 &&
        style->width == 2 && style->opacity == 60);
  CHECK(dispatch(map, nullptr, MS_SUCCESS) == baseline);

  for (const char *invalid :
       {"", "red:-1", "red:101", "red:40.5", "red:nan", "red:999999999999",
        "red:40,", ",red:40", "red:40,,blue:75", "red:40,RED:50",
        "red:40,unknown:20", "colors:40", "root:40"}) {
    const std::string output = dispatch(map, invalid, MS_FAILURE);
    CHECK(output.find("InvalidParameterValue") != std::string::npos);
    CHECK(red->compositer == compositer && compositer->opacity == 80);
    CHECK(blue->compositer == nullptr);
    CHECK(dispatch(map, nullptr, MS_SUCCESS) == baseline);
  }
  CHECK(dispatch(map, "blue:40", MS_FAILURE, "red")
            .find("InvalidParameterValue") != std::string::npos);
  CHECK(dispatch(map, nullptr, MS_SUCCESS) == baseline);

  // Also restore opacity on errors raised after applying the parameter.
  msLayerSetProcessingKey(red, "RENDERMODE", "INVALID");
  CHECK(
      dispatch(map, "red:40,blue:75", MS_FAILURE).find("Unknown RENDERMODE") !=
      std::string::npos);
  CHECK(red->compositer == compositer && compositer->opacity == 80);
  CHECK(blue->compositer == nullptr);
  msLayerSetProcessingKey(red, "RENDERMODE", nullptr);
  CHECK(dispatch(map, nullptr, MS_SUCCESS) == baseline);
  msFreeMap(map);
}

int main() {
  CHECK(msSetup() == MS_SUCCESS);
  testAPI();
  testReusedMap();
  msCleanup();
  return failures ? 1 : 0;
}
