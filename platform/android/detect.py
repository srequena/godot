import os
import sys
import platform
import subprocess

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from SCons import Environment


def is_active():
    return True


def get_name():
    return "Android"


def can_build():
    return os.path.exists(get_env_android_sdk_root())


def get_opts():
    return [
        ("ANDROID_SDK_ROOT", "Path to the Android SDK", get_env_android_sdk_root()),
        ("ndk_platform", 'Target platform (android-<api>, e.g. "android-24")', "android-24"),
    ]


# Return the ANDROID_SDK_ROOT environment variable.
def get_env_android_sdk_root():
    return os.environ.get("ANDROID_SDK_ROOT", -1)


def get_min_sdk_version(platform):
    return int(platform.split("-")[1])


def get_android_ndk_root(env):
    return env["ANDROID_SDK_ROOT"] + "/ndk/" + get_ndk_version()


# This is kept in sync with the value in 'platform/android/java/app/config.gradle'.
def get_ndk_version():
    return "23.2.8568313"


def get_flags():
    return [
        ("arch", "arm64"),  # Default for convenience.
        ("target", "template_debug"),
    ]


# Check if Android NDK version is installed
# If not, install it.
def install_ndk_if_needed(env):
    print("Checking for Android NDK...")
    sdk_root = env["ANDROID_SDK_ROOT"]
    if not os.path.exists(get_android_ndk_root(env)):
        extension = ".bat" if os.name == "nt" else ""
        sdkmanager = sdk_root + "/cmdline-tools/latest/bin/sdkmanager" + extension
        if os.path.exists(sdkmanager):
            # Install the Android NDK
            print("Installing Android NDK...")
            ndk_download_args = "ndk;" + get_ndk_version()
            subprocess.check_call([sdkmanager, ndk_download_args])
        else:
            print("Cannot find " + sdkmanager)
            print(
                "Please ensure ANDROID_SDK_ROOT is correct and cmdline-tools are installed, or install NDK version "
                + get_ndk_version()
                + " manually."
            )
            sys.exit()
    env["ANDROID_NDK_ROOT"] = get_android_ndk_root(env)


def configure(env: "Environment"):
    # Validate arch.
    supported_arches = ["x86_32", "x86_64", "arm32", "arm64"]
    if env["arch"] not in supported_arches:
        print(
            'Unsupported CPU architecture "%s" for Android. Supported architectures are: %s.'
            % (env["arch"], ", ".join(supported_arches))
        )
        sys.exit()

    install_ndk_if_needed(env)
    ndk_root = env["ANDROID_NDK_ROOT"]

    # Architecture

    if get_min_sdk_version(env["ndk_platform"]) < 21 and env["arch"] in ["x86_64", "arm64"]:
        print(
            'WARNING: arch="%s" is not supported with "ndk_platform" lower than "android-21". Forcing platform 21.'
            % env["arch"]
        )
        env["ndk_platform"] = "android-21"

    if env["arch"] == "arm32":
        target_triple = "armv7a-linux-androideabi"
    elif env["arch"] == "arm64":
        target_triple = "aarch64-linux-android"
    elif env["arch"] == "x86_32":
        target_triple = "i686-linux-android"
    elif env["arch"] == "x86_64":
        target_triple = "x86_64-linux-android"

    target_option = ["-target", target_triple + str(get_min_sdk_version(env["ndk_platform"]))]
    env.Append(ASFLAGS=[target_option, "-c"])
    env.Append(CCFLAGS=target_option)
    env.Append(LINKFLAGS=target_option)

    # LTO

    if env["lto"] == "auto":  # LTO benefits for Android (size, performance) haven't been clearly established yet.
        env["lto"] = "none"

    if env["lto"] != "none":
        if env["lto"] == "thin":
            env.Append(CCFLAGS=["-flto=thin"])
            env.Append(LINKFLAGS=["-flto=thin"])
        else:
            env.Append(CCFLAGS=["-flto"])
            env.Append(LINKFLAGS=["-flto"])

    # Compiler configuration

    env["SHLIBSUFFIX"] = ".so"

    if env["PLATFORM"] == "win32":
        env.use_windows_spawn_fix()

    if sys.platform.startswith("linux"):
        host_subpath = "linux-x86_64"
    elif sys.platform.startswith("darwin"):
        host_subpath = "darwin-x86_64"
    elif sys.platform.startswith("win"):
        if platform.machine().endswith("64"):
            host_subpath = "windows-x86_64"
        else:
            host_subpath = "windows"

    toolchain_path = ndk_root + "/toolchains/llvm/prebuilt/" + host_subpath
    compiler_path = toolchain_path + "/bin"

    env["CC"] = compiler_path + "/clang"
    env["CXX"] = compiler_path + "/clang++"
    env["AR"] = compiler_path + "/llvm-ar"
    env["RANLIB"] = compiler_path + "/llvm-ranlib"
    env["AS"] = compiler_path + "/clang"

    # Disable exceptions on template builds
    if not env.editor_build:
        env.Append(CXXFLAGS=["-fno-exceptions"])

    env.Append(
        CCFLAGS=(
            "-fpic -ffunction-sections -funwind-tables -fstack-protector-strong -fvisibility=hidden -fno-strict-aliasing".split()
        )
    )
    env.Append(CPPDEFINES=["GLES_ENABLED"])

    if get_min_sdk_version(env["ndk_platform"]) >= 24:
        env.Append(CPPDEFINES=[("_FILE_OFFSET_BITS", 64)])

    if env["arch"] == "x86_32":
        # The NDK adds this if targeting API < 24, so we can drop it when Godot targets it at least
        env.Append(CCFLAGS=["-mstackrealign"])
    elif env["arch"] == "arm32":
        env.Append(CCFLAGS="-march=armv7-a -mfloat-abi=softfp".split())
        env.Append(CPPDEFINES=["__ARM_ARCH_7__", "__ARM_ARCH_7A__"])
        env.Append(CPPDEFINES=["__ARM_NEON__"])
    elif env["arch"] == "arm64":
        env.Append(CCFLAGS=["-mfix-cortex-a53-835769"])
        env.Append(CPPDEFINES=["__ARM_ARCH_8A__"])

    # Link flags

    env.Append(LINKFLAGS="-Wl,--gc-sections -Wl,--no-undefined -Wl,-z,now".split())
    env.Append(LINKFLAGS="-Wl,-soname,libgodot_android.so")

    env.Prepend(CPPPATH=["#platform/android"])
    env.Append(CPPDEFINES=["ANDROID_ENABLED", "UNIX_ENABLED"])
    env.Append(LIBS=["OpenSLES", "EGL", "GLESv2", "android", "log", "z", "dl"])

    if env["vulkan"]:
        env.Append(CPPDEFINES=["VULKAN_ENABLED"])
        if not env["use_volk"]:
            env.Append(LIBS=["vulkan"])
