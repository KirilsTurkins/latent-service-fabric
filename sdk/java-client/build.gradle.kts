plugins {
    `java-library`
}

group = "dev.latent"
version = "0.1.0-alpha.3"

java {
    toolchain {
        languageVersion.set(JavaLanguageVersion.of(21))
    }
}

repositories {
    mavenCentral()
}

val prepareTransport by tasks.registering(Exec::class) {
    workingDir(rootDir.parentFile.parentFile)
    commandLine("python3", "sdk/java-client/tools/build.py", "prepare")
}

sourceSets {
    main {
        java.srcDirs("src/transport/java", "src/example/java", "build/generated/java")
    }
    test {
        java.srcDir("src/transportTest/java")
    }
}

dependencies {
    api(fileTree("build/deps") { include("*.jar") })
}

tasks.compileJava { dependsOn(prepareTransport); options.release.set(21) }
tasks.compileTestJava { options.release.set(21) }

val semanticTest by tasks.registering(JavaExec::class) {
    dependsOn(tasks.testClasses)
    classpath = sourceSets.test.get().runtimeClasspath
    mainClass.set("dev.latent.sdk.InvocationIdentityTest")
}

val transportTest by tasks.registering(JavaExec::class) {
    dependsOn(tasks.testClasses)
    workingDir(rootDir.parentFile.parentFile)
    classpath = sourceSets.test.get().runtimeClasspath
    mainClass.set("dev.latent.sdk.transport.TransportTest")
    enableAssertions = true
}

tasks.check { dependsOn(semanticTest, transportTest) }
