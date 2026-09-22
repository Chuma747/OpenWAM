#include "TEjeTurbogrupo.h"
#include "TController.h"
#include "LiveResults.h"
#include <cassert>
#include <cmath>
#include <fstream>

class PrescribedSpeed : public TController {
public:
    PrescribedSpeed() : TController(static_cast<nmControlMethod>(0), 0) {}
    double Output(double time) override { return time <= 1. ? 10000. : 20000.; }
    void LeeController(const char*, fpos_t&) override {}
    void AsignaObjetos(TSensor**, TController**) override {}
    void LeeResultadosMedControlador(const char*, fpos_t&) override {}
    void LeeResultadosInsControlador(const char*, fpos_t&) override {}
    void CabeceraResultadosMedControlador(std::stringstream&) override {}
    void CabeceraResultadosInsControlador(std::stringstream&) override {}
    void ImprimeResultadosMedControlador(std::stringstream&) override {}
    void ImprimeResultadosInsControlador(std::stringstream&) override {}
    void IniciaMedias() override {}
    void ResultadosMediosController() override {}
    void AcumulaResultadosMediosController(double) override {}
    void ResultadosInstantController() override {}
};

int main(int argc, char** argv) {
    assert(argc == 2);
    { std::ofstream fixture(argv[1]); fixture << "45000 1 0 0 1 0\n"; }
    FILE* fixture = fopen(argv[1], "r");
    fpos_t start;
    fgetpos(fixture, &start);
    fclose(fixture);
    TEjeTurbogrupo shaft(0, 4);
    shaft.IniciaMedias();
    shaft.ReadTurbochargerAxis(argv[1], start, nullptr, nullptr);
    PrescribedSpeed speed;
    TController* controllers[] = {&speed};
    shaft.AsignaRPMController(controllers);
    // No average-output selection was read. Unequal intervals still produce a mean.
    shaft.CalculaEjesTurbogrupo(10., nmEstacionario, 1., 10.);
    shaft.CalculaEjesTurbogrupo(20., nmEstacionario, 3., 20.);
    shaft.ResultadosMediosEje();
    assert(std::abs(shaft.AverageSpeed() - 50000. / 3.) < 1e-9);
    shaft.ResultadosMediosEje();  // Multiple readers must not change the snapshot.
    assert(std::abs(shaft.AverageSpeed() - 50000. / 3.) < 1e-9);
    shaft.CalculaEjesTurbogrupo(30., nmEstacionario, 4., 30.);
    shaft.ResultadosMediosEje();
    assert(shaft.AverageSpeed() == 20000.);
    assert(LiveResults::number(std::nan("")) == "null");
    assert(LiveResults::number(INFINITY) == "null");
    assert(LiveResults::quote("a\nb\"c") == "\"a\\u000ab\\\"c\"");
}
