#include <fstream>
#include <sstream>
#include <iostream>
#include <thread>
#include <mutex>
#include <vector>
#include <deque>
#include <random>
#include "argparse.hpp"
#include "date.h"

// this is why they call C++ cancer
typedef std::chrono::time_point<std::chrono::system_clock, std::chrono::microseconds> timestamp;

#define ROLL_MIN 10
#define ROLL_MAX 560
#define ROLL_SCALE 1

double DIP_MAX=0.2;
double SELL_MAX=0.2;

#define MAKER_FEE 0.005
#define TAKER_FEE 0.005

struct Record {
    long long time;
    double price;
    double max;
    double change;

    Record(const std::string& line) {
        //14229070888,BTC-EUR,40999.76,40999.76,41006.87,sell,2022-01-05T08:20:36.479940Z,57916989
        std::stringstream ss(line);
        std::string part;
        int i=0;
        while(std::getline(ss, part, ',')){
            if(i == 2) {    // price
                price = atof(part.c_str());
            } else if(i == 6){  // time
                std::istringstream ss(part);
                timestamp t;
                ss >> date::parse("%FT%TZ", t);
                time = t.time_since_epoch().count();
            }
            i++;
        }
    }
};

std::vector<Record> roll(const std::vector<Record>& records, long long minutes){
    long long window = minutes * 60000000;
    std::vector<Record> copy(records);
    std::deque<Record> frame;

    double maxSoFar = 0.0;
    long long maxTime = 0;

    // This implementation is inefficient as hell, but simple enough
    for(size_t i=0; i<copy.size(); i++){
        Record& now = copy[i];
        frame.emplace_back(now);
        if(now.price > maxSoFar){
            maxSoFar = now.price;
            maxTime = now.time;
        }

        long long bound = now.time - window;
        while(!frame.empty() && frame.front().time < bound){
            frame.pop_front();
        }

        if(maxTime < bound){
            maxSoFar = 0.0;
        }

        if(maxSoFar == 0.0){
            for(Record& rec : frame){
                if(rec.price > maxSoFar){
                    maxSoFar = rec.price;
                    maxTime = rec.time;
                }
            }
        }

        now.max = maxSoFar;
        now.change = 0.0;
        if(i > 0){
            now.change = now.price / copy[i - 1].max - 1.0;
        }
    }
    return copy;
}

class Chad {
public:
    double _buy = -0.01;
    double _sell = 0.01;
    double _ccy = 0.0;
    double _crypto = 0.0;
    double _buyPrice = -1.0;
    int _buys = 0;
    int _sells = 0;

    Chad() {

    }

    Chad(double cash, double buy, double sell){
        _ccy = cash;
        _buy = buy;
        _sell = sell;
    }

    bool will_buy(double change, double price) const {
        return _ccy > 0 && change <= _buy;
    }
    
    bool will_sell(double change, double price) const {
        return _buyPrice >= 0 && (price / _buyPrice - 1.0) >= (_sell + MAKER_FEE + TAKER_FEE);
    }
    
    void buy(double price){
        double amt = (_ccy / price / (1 + MAKER_FEE));
        amt = floor(amt * 1000000.0) / 1000000.0;
        if(amt <= 0.0) return;
        _ccy -= amt * price * (1 + MAKER_FEE);
        _crypto += amt;
        _buyPrice = price;
        _buys++;
    }
        
    void sell(double price){
        _ccy += _crypto * price * (1 - TAKER_FEE);
        _crypto = 0;
        _buyPrice = -1.0;
        _sells++;
    }

    double equity(double price) const {
        return _ccy; // + _crypto * price / (1.0 + MAKER_FEE);
    }

    double step(const Record& record) {
        if(will_buy(record.change, record.price)){
            buy(record.price);
        } else if(will_sell(record.change, record.price)){
            sell(record.price);
        }
        return equity(record.price);
    }

};

std::vector<Record> rolls[(ROLL_MAX + 1) * ROLL_SCALE];

double best = 0.0;
std::mutex mtx;

void worker(){
    std::random_device dev;
    std::mt19937 rng(dev());
    std::uniform_int_distribution<std::mt19937::result_type> wnd(ROLL_MIN, ROLL_MAX);
    std::uniform_real_distribution<double> dbl;

    while(true){
        int window = wnd(rng) * ROLL_SCALE;
        double buy = dbl(rng) * -DIP_MAX;
        double sell = dbl(rng) * SELL_MAX;
        Chad ch(1000.0, buy, sell);
        std::vector<Record>& arr = rolls[window];
        for(Record& rec : arr){
            ch.step(rec);
        }
        double eq = ch.equity(arr.back().price);
        mtx.lock();
        if(eq > best){
            best = eq;
            printf("Chad(buy=%.6f, sell=%.6f, window=%d): %.3f | buys=%d, sells=%d\n", buy, sell, window, eq, ch._buys, ch._sells);
        }
        mtx.unlock();
    }
}

int main(int argc, const char **argv){
    argparse::ArgumentParser parser("simulation");
    
    parser
        .add_argument("--pair")
        .default_value<std::string>("LTC-EUR")
        .help("traded pair, i.e. BTC-EUR");

    parser
        .add_argument("--csv")
        .default_value<std::string>("../stock_dataset.csv")
        .help("input dataset");

    parser
        .add_argument("--buy")
        .default_value<double>(0.05)
        .help("buy threshold")
        .scan<'f', double>();

    parser
        .add_argument("--sell")
        .default_value<double>(0.05)
        .help("sell threshold")
        .scan<'f', double>();

    try {
        parser.parse_args(argc, argv);
    } catch(const std::runtime_error& err) {
        std::cerr << err.what() << std::endl;
        std::cerr << parser;
        return 1;
    }

    
    std::string target = parser.get<std::string>("pair");
    std::string line;
    DIP_MAX = parser.get<double>("buy");
    SELL_MAX = parser.get<double>("sell");

    std::cout << "Loading data for " << target << " in " << parser.get<std::string>("csv") <<  std::endl;

    std::vector<Record> records;
    std::ifstream f(parser.get<std::string>("csv"));
    if(!f.is_open()){
        std::cerr << "Couldn't open input dataset!" << std::endl;
        return 1;
    }

    while(std::getline(f, line)){
        if(line.find(target) == std::string::npos) continue;
        records.emplace_back(Record(line));
    }

    std::cout << "Precomputing rolling maxes" << std::endl;

    for(int i=ROLL_MIN; i<=ROLL_MAX; i++){
        //std::cout << "Precomputing rolling max with window " << (i * ROLL_SCALE) << std::endl;
        rolls[i * ROLL_SCALE] = roll(records, i * ROLL_SCALE);
    }

    std::cout << "Simulating" << std::endl;
    std::vector<std::thread> threads;
    for(unsigned int i=0; i<std::thread::hardware_concurrency(); i++){
        threads.emplace_back(std::thread(worker));
    }
    for(std::thread& thr : threads){
        thr.join();
    }
}