/*
 * Decompiled with CFR 0.152.
 */
package ca.mc.exchange_simulator.traders;

import ca.mc.exchange_simulator.core.DeterministicRandom;
import ca.mc.exchange_simulator.core.MarketSnapshot;
import ca.mc.exchange_simulator.core.Order;
import ca.mc.exchange_simulator.traders.BaseTrader;
import java.util.ArrayList;
import java.util.List;

public class MarketMaker
extends BaseTrader {
    private double gamma;
    private double deltaMM;
    private int inventoryLimit;
    private int safeInventory;
    private int restPeriod;
    private double spreadEdge;
    private double fundamentalValue;
    private int stressedMode = 0;
    private int restartStep = 0;

    public MarketMaker(String traderId, DeterministicRandom rng, int inventoryLimit, double spreadEdge) {
        this(traderId, rng, inventoryLimit, 101, 12000, spreadEdge, 0.5, 0.05, 1000.0);
    }

    public MarketMaker(String traderId, DeterministicRandom rng, int inventoryLimit, double spreadEdge, double fundamentalValue) {
        this(traderId, rng, inventoryLimit, 101, 12000, spreadEdge, 0.5, 0.05, fundamentalValue);
    }

    public MarketMaker(String traderId, DeterministicRandom rng, int inventoryLimit, int safeInventory, int restPeriod, double spreadEdge, double gamma, double deltaMM, double fundamentalValue) {
        super(traderId, rng);
        this.inventoryLimit = inventoryLimit;
        this.safeInventory = safeInventory;
        this.restPeriod = restPeriod;
        this.spreadEdge = spreadEdge;
        this.gamma = gamma;
        this.deltaMM = deltaMM;
        this.fundamentalValue = fundamentalValue;
    }

    @Override
    public List<Order> decide(MarketSnapshot snapshot) {
        ArrayList<Order> orders = new ArrayList<Order>();
        double bestBid = snapshot.getBid();
        double bestAsk = snapshot.getAsk();
        double currentPrice = bestBid == 0.0 && bestAsk == 0.0 ? 0.0 : (bestBid == 0.0 ? bestAsk : (bestAsk == 0.0 ? bestBid : (bestBid + bestAsk) / 2.0));
        if (currentPrice == 0.0 && this.fundamentalValue > 0.0) {
            currentPrice = this.fundamentalValue;
        }
        if (currentPrice == 0.0) {
            return orders;
        }
        int currentStep = snapshot.getStep();
        if (Math.abs(this.position) >= this.inventoryLimit) {
            this.stressedMode = 1;
            this.restartStep = currentStep + this.restPeriod;
        }
        if (this.stressedMode == 1 && Math.abs(this.position) <= this.safeInventory) {
            this.stressedMode = 0;
        }
        if (this.stressedMode == 1) {
            ArrayList toCancel = new ArrayList(this.activeOrderIds);
            for (String orderId : toCancel) {
                orders.add(this.createCancelOrder(orderId));
            }
            if (this.position > 0) {
                orders.add(this.createMarketOrder("SELL", Math.min(this.position, 500)));
            } else if (this.position < 0) {
                orders.add(this.createMarketOrder("BUY", Math.min(-this.position, 500)));
            }
        } else if (currentStep >= this.restartStep) {
            if (this.rng.nextDouble() < this.deltaMM) {
                ArrayList toCancel = new ArrayList(this.activeOrderIds);
                for (String orderId : toCancel) {
                    orders.add(this.createCancelOrder(orderId));
                }
            }
            if (this.rng.nextDouble() < this.gamma) {
                double priceDistance = this.rng.nextDouble() * this.spreadEdge;
                if (priceDistance < 0.1) {
                    priceDistance = 0.1;
                }
                double bidP = currentPrice - priceDistance;
                Order bid = this.createLimitOrder("BUY", (double)Math.round(bidP * 10.0) / 10.0, 500);
                orders.add(bid);
                double askP = currentPrice + priceDistance;
                Order ask = this.createLimitOrder("SELL", (double)Math.round(askP * 10.0) / 10.0, 500);
                orders.add(ask);
            }
        }
        return orders;
    }

    public void setInventoryLimit(int limit) {
        this.inventoryLimit = limit;
    }

    public void setDelta(double delta) {
        this.deltaMM = delta;
    }
}
