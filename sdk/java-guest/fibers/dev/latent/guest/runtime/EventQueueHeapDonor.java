package dev.latent.guest.runtime;

/** Template for the pinned EventQueue's private heap operation, not a public queue. */
final class EventQueueHeapDonor {
    private EventQueueHeapDonor() { }
    private static Node[] data;
    private static int size;

    private static final class Node {
        final long time;
        Node(long time) { this.time = time; }
    }

    private static void update(int index) {
        Node item = data[index];
        // Arbitrary cancellation can move the old last node under a later
        // parent. Restore that half of the heap before the existing down sift.
        while (index > 0) {
            int parent = (index - 1) >>> 1;
            if (data[parent].time <= item.time) break;
            data[index] = data[parent];
            index = parent;
        }
        while (true) {
            int left = index * 2 + 1;
            int right = left + 1;
            int next;
            if (left >= size) break;
            else if (right >= size || data[left].time < data[right].time) next = left;
            else next = right;
            if (item.time <= data[next].time) break;
            data[index] = data[next];
            index = next;
        }
        data[index] = item;
    }
}
