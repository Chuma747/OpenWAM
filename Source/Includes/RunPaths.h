#ifndef OPENWAM_RUN_PATHS_H
#define OPENWAM_RUN_PATHS_H
#include <string>

// Shared by legacy diagnostic writers which otherwise use the working directory.
inline std::string& runOutputDirectory() {
    static std::string directory;
    return directory;
}
inline std::string runOutputPath(const std::string& name) {
    return runOutputDirectory().empty() ? name : runOutputDirectory() + "/" + name;
}
#endif
