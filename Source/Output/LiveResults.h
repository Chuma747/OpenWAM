#ifndef OPENWAM_LIVE_RESULTS_H
#define OPENWAM_LIVE_RESULTS_H

#include <chrono>
#include <cmath>
#include <fstream>
#include <iomanip>
#include <locale>
#include <sstream>
#include <stdexcept>
#include <string>

// A GUI-independent, append-only protocol. Each committed record ends in '\n'.
class LiveResults {
    std::ofstream file;
    std::chrono::steady_clock::time_point flushed;
public:
    bool configured = false;
    double nextAngle = 0., intervalStart = 0., intervalAngle = 0.;
    bool enabled() const { return file.is_open(); }
    static std::string quote(const std::string& value) {
        std::ostringstream out;
        out << '"';
        for(unsigned char c : value) {
            if(c == '"' || c == '\\') out << '\\' << c;
            else if(c < 32) out << "\\u" << std::hex << std::setw(4) << std::setfill('0') << int(c);
            else out << c;
        }
        out << '"';
        return out.str();
    }
    static std::string number(double value) {
        if(!std::isfinite(value)) return "null";
        std::ostringstream out;
        out.imbue(std::locale::classic());
        out << std::setprecision(17) << value;
        return out.str();
    }
    void open(const std::string& path) {
        file.open(path.c_str(), std::ios::out | std::ios::trunc);
        if(!file) throw std::runtime_error("Cannot open results stream: " + path);
        flushed = std::chrono::steady_clock::now();
    }
    void write(const std::string& record, bool force = false) {
        if(!enabled()) return;
        file << record << '\n';
        flush(force);
        if(!file) throw std::runtime_error("Cannot write results stream (check disk space)");
    }
    void flush(bool force = false) {
        if(!enabled()) return;
        auto now = std::chrono::steady_clock::now();
        if(force || now - flushed >= std::chrono::milliseconds(200)) {
            file.flush();
            flushed = now;
        }
    }
    void finish(const std::string& status, const std::string& message = "") {
        write("{\"type\":\"end\",\"status\":" + quote(status) + ",\"message\":" + quote(message) + "}", true);
    }
};
#endif
