#include "TOpenWAM.h"
#include <ctime>

namespace {
using Values = std::vector<std::pair<std::string, double> >;
std::string valuesJson(const Values& values) {
    std::string out = "{";
    for(const auto& value : values) {
        if(out.size() > 1) out += ',';
        out += LiveResults::quote(value.first) + ':' + LiveResults::number(value.second);
    }
    return out + '}';
}
std::string component(const std::string& type, int id) {
    return type + "." + std::to_string(id);
}
void channel(std::string& list, const std::string& owner, const std::string& field,
             const std::string& label, const std::string& unit, const std::string& kind) {
    if(list.size() > 1) list += ',';
    list += "{\"id\":" + LiveResults::quote(owner + "." + field)
        + ",\"component\":" + LiveResults::quote(owner) + ",\"label\":" + LiveResults::quote(label)
        + ",\"unit\":" + LiveResults::quote(unit) + ",\"kind\":" + LiveResults::quote(kind) + '}';
}
}

void TOpenWAM::StartLiveResults(const std::string& path, const std::string& input) {
    if(path.empty()) return;
    Live.open(path);
    Live.write("{\"type\":\"run\",\"schema_version\":1,\"input\":" + LiveResults::quote(input)
        + ",\"started_unix\":" + std::to_string(std::time(NULL))
        + ",\"run_id\":" + LiveResults::quote(path) + "}", true);
}

void TOpenWAM::PublishLiveStep() {
    if(!Live.enabled()) return;
    const double duration = EngineBlock ? Engine[0]->getAngTotalCiclo() : 720.;
    if(!Live.configured) {
        std::string channels = "[";
        if(EngineBlock) {
            for(const auto& item : std::vector<std::vector<std::string> >{
                {"power", "Effective power (mechanism)", "kW"}, {"power_cycle", "Effective power (cycle)", "kW"},
                {"torque", "Effective torque", "Nm"}, {"torque_cycle", "Effective torque (cycle)", "Nm"},
                {"bmep", "BMEP (cycle)", "bar"}, {"rpm", "Engine speed", "rpm"},
                {"fuel", "Fuel per cylinder per cycle", "kg/cycle"}, {"bsfc", "BSFC", "g/kWh"}})
                channel(channels, "engine.1", item[0], item[1], item[2], "average");
            for(int i = 0; i < Engine[0]->getGeometria().NCilin; ++i) {
                const std::string owner = component("cylinder", i + 1);
                channel(channels, owner, "pressure", "Cylinder pressure", "bar", "trace");
                channel(channels, owner, "temperature", "Cylinder temperature", "degC", "trace");
                channel(channels, owner, "intake_flow", "Intake flow (positive into cylinder)", "kg/s", "trace");
                channel(channels, owner, "exhaust_flow", "Exhaust flow (positive out of cylinder)", "kg/s", "trace");
            }
        }
        for(int i = 0; i < NumberOfAxis; ++i)
            channel(channels, component("shaft", i + 1), "rpm", "Turbocharger speed", "rpm", "average");
        for(int i = 0; i < NumberOfCompressors; ++i) {
            auto owner = component("compressor", i + 1);
            channel(channels, owner, "work", "Compressor work", "J", "average");
            channel(channels, owner, "efficiency", "Compressor efficiency", "1", "average");
            channel(channels, owner, "flow", "Compressor mass flow", "kg/s", "average");
            channel(channels, owner, "ratio", "Compressor pressure ratio", "1", "average");
        }
        for(int i = 0; i < NumberOfTurbines; ++i) {
            auto owner = component("turbine", i + 1);
            channel(channels, owner, "work", "Turbine work", "J", "average");
            channel(channels, owner, "efficiency", "Turbine efficiency", "1", "average");
        }
        Live.write("{\"type\":\"channels\",\"cycle_degrees\":" + LiveResults::number(duration)
            + ",\"sample_degrees\":1,\"channels\":" + channels + "]}", true);
        Live.configured = true;
        Live.nextAngle = Theta;
        Live.intervalStart = AcumulatedTime;
        Live.intervalAngle = Theta;
    }
    if(Theta < Live.nextAngle) { Live.flush(); return; }
    Live.nextAngle = std::floor(Theta) + 1.;
    Values values, angles;
    if(EngineBlock) {
        for(int i = 0; i < Engine[0]->getGeometria().NCilin; ++i) {
            auto cylinder = Engine[0]->GetCilindro(i);
            auto owner = component("cylinder", i + 1);
            values.push_back({owner + ".pressure", cylinder->getPressure()});
            values.push_back({owner + ".temperature", cylinder->getTemperature()});
            double intake = 0., exhaust = 0.;
            for(int j = 0; j < cylinder->getNumeroUnionesAdm(); ++j)
                intake -= dynamic_cast<TCCCilindro*>(cylinder->GetCCValvulaAdm(j))->getMassflow();
            for(int j = 0; j < cylinder->getNumeroUnionesEsc(); ++j)
                exhaust += dynamic_cast<TCCCilindro*>(cylinder->GetCCValvulaEsc(j))->getMassflow();
            values.push_back({owner + ".intake_flow", intake});
            values.push_back({owner + ".exhaust_flow", exhaust});
            angles.push_back({owner, std::fmod(cylinder->getAnguloActual() + duration, duration)});
        }
    }
    Live.write("{\"type\":\"sample\",\"kind\":\"trace\",\"time\":" + LiveResults::number(AcumulatedTime)
        + ",\"cycle\":" + std::to_string(int(std::floor(Theta / duration)))
        + ",\"angle\":" + LiveResults::number(std::fmod(Theta, duration))
        + ",\"absolute_angle\":" + LiveResults::number(Theta)
        + ",\"progress\":" + LiveResults::number(100. * (Theta - ThetaIni) / (thmax - ThetaIni))
        + ",\"local_angles\":" + valuesJson(angles) + ",\"values\":" + valuesJson(values) + '}');
}

void TOpenWAM::PublishLiveCycle() {
    if(!Live.enabled() || !EngineBlock) return;
    const auto& result = Engine[0]->AverageResults();
    Values values = {{"engine.1.power", result.PotenciaMED}, {"engine.1.power_cycle", result.PotenciaCicloMED},
        {"engine.1.torque", result.ParEfectivoMED}, {"engine.1.torque_cycle", result.ParEfectivoCicloMED},
        {"engine.1.bmep", result.PMECicloMED}, {"engine.1.rpm", result.RegimenGiroMED},
        {"engine.1.fuel", result.MasaFuelMED}, {"engine.1.bsfc", result.ConsumoEspecificoMED}};
    for(int i = 0; i < NumberOfAxis; ++i)
        values.push_back({component("shaft", i + 1) + ".rpm", Axis[i]->AverageSpeed()});
    for(int i = 0; i < NumberOfCompressors; ++i) {
        auto owner = component("compressor", i + 1);
        values.push_back({owner + ".work", Compressor[i]->getTrabCiclo()});
        values.push_back({owner + ".efficiency", Compressor[i]->getRendMed()});
        values.push_back({owner + ".flow", Compressor[i]->getGastoMed()});
        values.push_back({owner + ".ratio", Compressor[i]->getRCMed()});
    }
    for(int i = 0; i < NumberOfTurbines; ++i) {
        auto owner = component("turbine", i + 1);
        values.push_back({owner + ".work", Turbine[i]->CycleWork()});
        values.push_back({owner + ".efficiency", Turbine[i]->CycleEfficiency()});
    }
    Live.write("{\"type\":\"sample\",\"kind\":\"average\",\"time\":" + LiveResults::number(AcumulatedTime)
        + ",\"cycle\":" + std::to_string(Engine[0]->getCiclo())
        + ",\"interval_start\":" + LiveResults::number(Live.intervalStart)
        + ",\"interval_angle_start\":" + LiveResults::number(Live.intervalAngle)
        + ",\"interval_angle_end\":" + LiveResults::number(Theta)
        + ",\"partial\":" + (std::fabs(Theta - Live.intervalAngle - Engine[0]->getAngTotalCiclo()) > 1. ? "true" : "false")
        + ",\"values\":" + valuesJson(values) + '}', true);
    Live.intervalStart = AcumulatedTime;
    Live.intervalAngle = Theta;
}
