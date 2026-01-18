/*
 * Decompiled with CFR 0.152.
 */
package ca.mc.exchange_simulator.traders;

import ca.mc.exchange_simulator.core.DeterministicRandom;
import ca.mc.exchange_simulator.core.MarketSnapshot;
import ca.mc.exchange_simulator.core.Order;
import ca.mc.exchange_simulator.traders.BaseTrader;
import java.util.ArrayList;
import java.util.LinkedList;
import java.util.List;

public class InstitutionalTrader
extends BaseTrader {
    private double percentageOfVolume;
    private int inventory;
    private int orderIntervalSteps;
    private int startStep;
    private int lastOrderStep = -1;
    private static final int VOLUME_WINDOW_STEPS = 600;
    private LinkedList<Integer> volumeHistory = new LinkedList();
    private int rollingVolume = 0;

    public InstitutionalTrader(String traderId, DeterministicRandom rng, int initialInventory, double percentageOfVolume, int orderIntervalSteps, int startStep) {
        super(traderId, rng);
        this.inventory = initialInventory;
        this.percentageOfVolume = percentageOfVolume;
        this.orderIntervalSteps = orderIntervalSteps;
        this.startStep = startStep;
    }

    @Override
    public List<Order> decide(MarketSnapshot snapshot) {
        ArrayList<Order> orders = new ArrayList<Order>();
        int currentStep = snapshot.getStep();
        int stepVolume = 0;
        if (snapshot.getTrades() != null) {
            for (MarketSnapshot.PublicTrade trade : snapshot.getTrades()) {
                stepVolume += trade.qty;
            }
        }
        this.updateVolumeHistory(stepVolume);
        if (currentStep < this.startStep) {
            return orders;
        }
        if (this.inventory <= 0) {
            return orders;
        }
        if (this.lastOrderStep >= 0 && currentStep - this.lastOrderStep < this.orderIntervalSteps) {
            return orders;
        }
        int marketVolume = Math.max(this.rollingVolume, 100);
        int targetVolume = (int)(this.percentageOfVolume * (double)marketVolume);
        int orderVolume = Math.min(targetVolume, this.inventory);
        if (orderVolume < 100) {
            orderVolume = Math.min(100, this.inventory);
        }
        if (orderVolume > 0) {
            orders.add(this.createMarketOrder("SELL", orderVolume));
            this.inventory -= orderVolume;
            this.lastOrderStep = currentStep;
        }
        return orders;
    }

    private void updateVolumeHistory(int stepVolume) {
        this.volumeHistory.addLast(stepVolume);
        this.rollingVolume += stepVolume;
        while (this.volumeHistory.size() > 600) {
            this.rollingVolume -= this.volumeHistory.removeFirst().intValue();
        }
    }

    public int getRemainingInventory() {
        return this.inventory;
    }
}
