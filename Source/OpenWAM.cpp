/*--------------------------------------------------------------------------------*\
|==========================|
 |\\   /\ /\   // O pen     | OpenWAM: The Open Source 1D Gas-Dynamic Code
 | \\ |  X  | //  W ave     |
 |  \\ \/_\/ //   A ction   | CMT-Motores Termicos / Universidad Politecnica Valencia
 |   \\/   \//    M odel    |
 ----------------------------------------------------------------------------------
 | License
 |
 |	This file is part of OpenWAM.
 |
 |	OpenWAM is free software: you can redistribute it and/or modify
 |	it under the terms of the GNU General Public License as published by
 |	the Free Software Foundation, either version 3 of the License, or
 |	(at your option) any later version.
 |
 |	OpenWAM is distributed in the hope that it will be useful,
 |	but WITHOUT ANY WARRANTY; without even the implied warranty of
 |	MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 |	GNU General Public License for more details.
 |
 |	You should have received a copy of the GNU General Public License
 |	along with OpenWAM.  If not, see <http://www.gnu.org/licenses/>.
 |
 \*--------------------------------------------------------------------------------*/

// ---------------------------------------------------------------------------
#ifdef __BORLANDC__
#include <vcl.h>
#endif

#pragma hdrstop

#include "TOpenWAM.h"
#include "labels.hpp"

// #include <tchar.h>
// ---------------------------------------------------------------------------

#pragma argsused


#include <cerrno>
#include "RunPaths.h"
#include <sys/stat.h>
#ifdef _WIN32
#include <direct.h>
#else
#include <unistd.h>
#endif

static std::string absolutePath(const std::string& path) {
#ifdef _WIN32
    char buffer[4096];
    if(!_fullpath(buffer, path.c_str(), sizeof(buffer))) throw std::runtime_error("Invalid path: " + path);
    return buffer;
#else
    if(!path.empty() && path[0] == '/') return path;
    char buffer[4096];
    if(!getcwd(buffer, sizeof(buffer))) throw std::runtime_error("Cannot determine working directory");
    return std::string(buffer) + "/" + path;
#endif
}

static void makeDirectory(const std::string& path) {
    for(size_t i = 1; i <= path.size(); ++i) {
        if(i != path.size() && path[i] != '/') continue;
        std::string part = path.substr(0, i);
#ifdef _WIN32
        int result = _mkdir(part.c_str());
#else
        int result = mkdir(part.c_str(), 0775);
#endif
        if(result != 0 && errno != EEXIST) throw std::runtime_error("Cannot create output directory: " + part);
    }
}

int main(int argc, char *argv[]) {
    std::string input, output, stream;
    try {
        for(int i = 1; i < argc; ++i) {
            std::string arg = argv[i];
            if(arg == "--help" || arg == "-h") {
                std::cout << "Usage: OpenWAM case.WAM [--output-dir DIR] [--results-stream FILE]\n";
                return 0;
            }
            if(arg == "--output-dir" || arg == "--results-stream") {
                if(++i == argc) throw std::runtime_error("Missing value for " + arg);
                (arg == "--output-dir" ? output : stream) = absolutePath(argv[i]);
            } else if(arg.compare(0, 2, "--") == 0 || !input.empty()) {
                throw std::runtime_error("Unexpected argument: " + arg);
            } else input = absolutePath(arg);
        }
        if(input.empty()) throw std::runtime_error("Usage: OpenWAM case.WAM [--output-dir DIR] [--results-stream FILE]");
        if(!output.empty()) makeDirectory(output);
        runOutputDirectory() = output;
        if(!output.empty()) {
            // Resolve referenced resources against the input, while isolating generated files.
            const std::string directory = input.substr(0, input.find_last_of("/\\"));
#ifdef _WIN32
            if(_chdir(directory.c_str()) != 0)
#else
            if(chdir(directory.c_str()) != 0)
#endif
                throw std::runtime_error("Cannot enter input directory: " + directory);
        }
        init_labels();
        TOpenWAM application;
        application.SetOutputDirectory(output);
        try {
            // Start with a run record, including during input parsing failures.
            application.StartLiveResults(stream, input);
            application.ReadInputData(&input[0]);
            application.ConnectFlowElements();
            application.ConnectControlElements();
            application.InitializeParameters();
            application.InitializeOutput();
            application.ProgressBegin();
            application.PublishLiveStep();
            do {
                application.Progress();
                if(application.IsIndependent()) application.DetermineTimeStepIndependent();
                else application.DetermineTimeStepCommon();
                application.NewEngineCycle();
                if(application.IsIndependent()) application.CalculateFlowIndependent();
                else application.CalculateFlowCommon();
                application.ManageOutput();
                application.PublishLiveStep();
            } while(!application.CalculationEnd());
            application.GeneralOutput();
            application.ProgressEnd();
            application.FinishLiveResults("completed");
        } catch(const std::exception& error) {
            application.FinishLiveResults("failed", error.what());
            throw;
        }
        return 0;
    } catch(const std::exception& error) {
        std::cerr << "ERROR: " << error.what() << std::endl;
        return 1;
    }
}
