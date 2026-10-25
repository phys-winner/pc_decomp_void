#include <regex>
#include <string>
#include "settings_regex.h"

int void_settings_regex_match(const char *pattern, const char *description) {
    if (!pattern || !description) return 0;
    try {
        const std::regex expression(std::string(pattern)+"$", std::regex::ECMAScript);
        return std::regex_search(description,expression) ? 1 : 0;
    } catch (const std::regex_error &) {
        return -1;
    }
}
