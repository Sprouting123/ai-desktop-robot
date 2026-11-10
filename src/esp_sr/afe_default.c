// AFE_CONFIG_DEFAULT() is a C99 designated-initializer macro that also needs
// the target's sdkconfig.h. Arduino builds do not include those headers from a
// C++ translation unit, so this tiny C wrapper returns the default config.
// Adapted from the Route A link check in experiment 016 phase 4.
#include "sdkconfig.h"
#include <stdbool.h>
#include <stddef.h>

#include "esp_afe_config.h"

afe_config_t wake_afe_default(void) {
  return (afe_config_t)AFE_CONFIG_DEFAULT();
}
