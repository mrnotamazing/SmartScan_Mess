"""Made-up student names for simulated data. Not real people."""

from __future__ import annotations

import random

FIRST = """Aarav Aditi Aditya Aisha Akash Ananya Anjali Arjun Arnav Avni Diya Dhruv Gauri Harsh Ishaan Isha
Kabir Kavya Krish Meera Mihir Myra Neha Nikhil Nisha Om Pooja Pranav Priya Rahul Riya Rohan Saanvi Sahil
Sameer Sana Shreya Siddharth Simran Sneha Tanvi Tara Varun Vedant Vihaan Yash Zara Farhan Imran Joseph
Maria Tenzin Lalit Gurpreet Harpreet Anushka Kunal Ritika Manav""".split()
LAST = """Sharma Verma Gupta Iyer Nair Reddy Rao Patel Shah Mehta Joshi Kulkarni Deshpande Banerjee Chatterjee
Das Ghosh Mukherjee Singh Kaur Gill Khan Ahmed Fernandes D'Souza Pillai Menon Chauhan Yadav Mishra Pandey
Tiwari Saxena Agarwal Bose Sen Naidu Hegde Kapoor Malhotra Arora Sethi Bhatt Trivedi Jain Thomas Lepcha""".split()


class NameMaker:
    def __init__(self, seed: int | str):
        self._rng = random.Random(f"names-{seed}")

    def next(self) -> str:
        return f"{self._rng.choice(FIRST)} {self._rng.choice(LAST)}"
