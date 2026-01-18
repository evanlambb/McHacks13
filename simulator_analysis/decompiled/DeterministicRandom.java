/*
 * Decompiled with CFR 0.152.
 */
package ca.mc.exchange_simulator.core;

import java.util.Random;

public class DeterministicRandom {
    private final Random random;
    private final long seed;

    public DeterministicRandom(long seed) {
        this.seed = seed;
        this.random = new Random(seed);
    }

    public double nextDouble() {
        return this.random.nextDouble();
    }

    public int nextInt(int bound) {
        return this.random.nextInt(bound);
    }

    public boolean nextBoolean() {
        return this.random.nextBoolean();
    }

    public long getSeed() {
        return this.seed;
    }

    public double nextLogNormal(double mu, double sigma) {
        double normal = this.random.nextGaussian();
        return Math.exp(mu + sigma * normal);
    }
}
