#pragma once
#include <PubSubClient.h>
#include "station_state.h"
#include "oregon_receiver.h"
#include "lacrosse_ws23xx.h"

// Pagine OLED selezionabili dalla Web UI.
static constexpr uint8_t DISPLAY_PAGE_ENVIRONMENT = 1U << 0;
static constexpr uint8_t DISPLAY_PAGE_WIND_RAIN   = 1U << 1;
static constexpr uint8_t DISPLAY_PAGE_TECHNOLINE  = 1U << 2;
static constexpr uint8_t DISPLAY_PAGE_PRESSURE    = 1U << 3;
static constexpr uint8_t DISPLAY_PAGE_STATUS      = 1U << 4;
static constexpr uint8_t DISPLAY_PAGE_ALL         = 0x1FU;

// Righe della pagina ESTERNO.
static constexpr uint8_t DISPLAY_ENV_TEMP_HUM = 1U << 0;
static constexpr uint8_t DISPLAY_ENV_DEW      = 1U << 1;
static constexpr uint8_t DISPLAY_ENV_HEAT_UV  = 1U << 2;
static constexpr uint8_t DISPLAY_ENV_BATTERY  = 1U << 3;
static constexpr uint8_t DISPLAY_ENV_ALL      = 0x0FU;

// Righe della pagina VENTO / PIOGGIA.
static constexpr uint8_t DISPLAY_WIND_SPEED_GUST = 1U << 0;
static constexpr uint8_t DISPLAY_WIND_DIRECTION  = 1U << 1;
static constexpr uint8_t DISPLAY_WIND_RAIN       = 1U << 2;
static constexpr uint8_t DISPLAY_WIND_BATTERY    = 1U << 3;
static constexpr uint8_t DISPLAY_WIND_ALL        = 0x0FU;

// Righe della pagina TECHNOLINE.
static constexpr uint8_t DISPLAY_TECH_TEMP_HUM   = 1U << 0;
static constexpr uint8_t DISPLAY_TECH_WIND_GUST  = 1U << 1;
static constexpr uint8_t DISPLAY_TECH_DIRECTION  = 1U << 2;
static constexpr uint8_t DISPLAY_TECH_RAIN       = 1U << 3;
static constexpr uint8_t DISPLAY_TECH_META       = 1U << 4;
static constexpr uint8_t DISPLAY_TECH_ALL        = 0x1FU;

// Righe della pagina BAROMETRO.
static constexpr uint8_t DISPLAY_PRESS_STATION   = 1U << 0;
static constexpr uint8_t DISPLAY_PRESS_ALTIMETER = 1U << 1;
static constexpr uint8_t DISPLAY_PRESS_TREND     = 1U << 2;
static constexpr uint8_t DISPLAY_PRESS_FORECAST  = 1U << 3;
static constexpr uint8_t DISPLAY_PRESS_ALL       = 0x0FU;

// Righe della pagina RF / STATUS.
static constexpr uint8_t DISPLAY_STATUS_OREGON   = 1U << 0;
static constexpr uint8_t DISPLAY_STATUS_DECODER  = 1U << 1;
static constexpr uint8_t DISPLAY_STATUS_TIMING   = 1U << 2;
static constexpr uint8_t DISPLAY_STATUS_TECH     = 1U << 3;
static constexpr uint8_t DISPLAY_STATUS_NETWORK  = 1U << 4;
static constexpr uint8_t DISPLAY_STATUS_ALL      = 0x1FU;

struct DisplayRuntimeConfig {
    uint8_t pageMask{DISPLAY_PAGE_ALL};
    uint8_t environmentFields{DISPLAY_ENV_ALL};
    uint8_t windRainFields{DISPLAY_WIND_ALL};
    uint8_t technolineFields{DISPLAY_TECH_ALL};
    uint8_t pressureFields{DISPLAY_PRESS_ALL};
    uint8_t statusFields{DISPLAY_STATUS_ALL};
    uint16_t pageIntervalSec{7};
    uint8_t contrast{255};
};

void initDisplay();
void serviceDisplayButton();
bool displayButtonEnabled();
int displayButtonPin();
bool displayEnabled();
void setDisplayEnabled(bool enabled);

DisplayRuntimeConfig getDisplayConfig();
bool validateDisplayConfig(const DisplayRuntimeConfig &cfg);
bool saveDisplayConfig(const DisplayRuntimeConfig &cfg, bool &changed);
bool resetDisplayConfigToDefaults(bool &changed);
uint8_t displayCurrentPage();

void updateDisplay(const StationState &state, const OregonRxStats &rxStats, const LaCrosseRxStats &lcStats, bool wifiOk, bool mqttOk);
