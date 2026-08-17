plugins {
    `java-library`
}

group = "dev.latent"
version = "0.1.0-alpha.0"

java {
    toolchain {
        languageVersion.set(JavaLanguageVersion.of(21))
    }
}

repositories {
    mavenCentral()
}
