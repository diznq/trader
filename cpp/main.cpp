#include <fstream>
#include <sstream>
#include <iostream>
#include <thread>
#include <mutex>
#include <vector>
#include <deque>
#include <random>
#include "date.h"

// this is why they call C++ cancer
typedef std::chrono::time_point<std::chrono::system_clock, std::chrono::microseconds> timestamp;

#define ROLL_MIN 3
#define ROLL_MAX 12
#define ROLL_SCALE 20

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
    // This implementation is inefficient as hell, but simple enough
    for(size_t i=0; i<copy.size(); i++){
        Record& now = copy[i];
        frame.emplace_back(now);
        long long bound = now.time - window;
        while(!frame.empty() && frame.front().time < bound){
            frame.pop_front();
        }
        double maxPrice = 0.0;
        for(Record& rec : frame){
            maxPrice = std::max(maxPrice, rec.price);
        }
        now.max = maxPrice;
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
    double _maker = 0.005;
    double _taker = 0.005;

    Chad() {

    }

    Chad(double cash, double buy, double sell){
        _ccy = cash;
        _buy = buy;
        _sell = sell;
    }

    bool will_buy(double change, double price) const {
        return change <= _buy;
    }
    
    bool will_sell(double change, double price) const {
        return _buyPrice >= 0 && (price / _buyPrice - 1.0) >= (_sell + _maker + _taker);
    }
    
    void buy(double price){
        double amt = (_ccy / price / (1 + _maker));
        _ccy -= amt * price * (1 + _maker);
        _crypto += amt;
        _buyPrice = price;
    }
        
    void sell(double price){
        _ccy += _crypto * price * (1 - _taker);
        _crypto = 0;
        _buyPrice = -1.0;
    }

    double equity(double price) const {
        return _ccy; // + _crypto * price / (1.0 + _maker);
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

std::vector<Record> rolls[1000];

double best = 0.0;
std::mutex mtx;

void worker(){
    std::random_device dev;
    std::mt19937 rng(dev());
    std::uniform_int_distribution<std::mt19937::result_type> wnd(ROLL_MIN, ROLL_MAX);
    std::uniform_real_distribution<double> dbl;

    while(true){
        int window = wnd(rng) * ROLL_SCALE;
        double buy = dbl(rng) * -0.1;
        double sell = dbl(rng) * 0.1;
        Chad ch(1000.0, buy, sell);
        std::vector<Record>& arr = rolls[window];
        for(Record& rec : arr){
            ch.step(rec);
        }
        double eq = ch.equity(arr.back().price);
        mtx.lock();
        if(eq > best){
            best = eq;
            printf("Chad(buy=%.6f, sell=%.6f, window=%d): %.3f\n", buy, sell, window, eq);
        }
        mtx.unlock();
    }
}

int main(int argc, const char **argv){
    const std::string target = argc >= 1 ? argv[1] : "BTC-EUR";
    std::vector<Record> records;
    std::ifstream f("../stock_dataset.csv");
    std::string line;

    std::cout << "Loading data for " << target << std::endl;

    while(std::getline(f, line)){
        if(line.find(target) == std::string::npos) continue;
        records.emplace_back(Record(line));
    }

    std::cout << "Precomputing rolling maxes" << std::endl;

    for(int i=ROLL_MIN; i<=ROLL_MAX; i++){
        std::cout << "Precomputing rolling max with window " << (i * ROLL_SCALE) << std::endl;
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